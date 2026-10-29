import asyncio
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import FollowEvent, ImageMessageContent, MessageEvent, TextMessageContent, VideoMessageContent

from . import line_io, oauth, reminders, runner

app = FastAPI()

scheduler = AsyncIOScheduler()

ALLOWED_USER_IDS = {
    u.strip() for u in os.environ.get("ALLOWED_USER_IDS", "").split(",") if u.strip()
}

# climbing mode is limited to these users (Steven); everyone else keeps the original behaviour
CLIMB_USER_IDS = {
    u.strip() for u in os.environ.get("CLIMB_USER_IDS", "").split(",") if u.strip()
}
CLIMB_IDLE_SECONDS = 3 * 3600
MAX_VIDEO_MS = 60_000

# per-user serial queues so messages from the same user are processed in order
_queues: dict[str, asyncio.Queue] = {}
_workers: dict[str, asyncio.Task] = {}


def _is_allowed(user_id: str) -> bool:
    # if allowlist is empty, allow everyone (useful for first local test)
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


def _climb_flag(user_id: str):
    return runner.user_dir(user_id) / "climb_mode"


def _in_climb(user_id: str) -> bool:
    f = _climb_flag(user_id)
    return user_id in CLIMB_USER_IDS and f.exists() and time.time() - f.stat().st_mtime < CLIMB_IDLE_SECONDS


def _prepare_video(user_id: str, video_id: str) -> str:
    src = runner.user_dir(user_id) / "inbox" / f"{video_id}.mp4"
    src.write_bytes(line_io.get_video_content(video_id))
    return runner.climb_video_prompt(user_id, video_id)


def _image_prompt(user_id: str, image_id: str, mode: str) -> str:
    if mode == "climb":
        path = runner.user_dir(user_id) / "inbox" / f"{image_id}.jpg"
        return f"[攀岩模式：使用者傳了一張圖片，路徑：{path}]\n請用 Read 看圖，依目前對話情境處理。"
    return (
        f"[使用者傳送了一張圖片，路徑：inbox/{image_id}.jpg]\n"
        "請看這張圖片的內容，並依使用者目前的對話情境處理"
        "（例如：如果是食物照片，記錄到飲食日記）。"
    )


def _send(user_id: str, reply_token: str, text: str, mode: str) -> None:
    try:
        line_io.reply_text(reply_token, text)
    except Exception:
        # climb turns (video download + analysis) can outlive the reply token -> fall back to push
        if mode != "climb":
            raise
        if reminders.try_record_push(runner.user_dir(user_id)):
            line_io.push_text(user_id, text)


async def _worker(user_id: str, queue: asyncio.Queue) -> None:
    while True:
        job = await queue.get()
        reply_token, text = job["reply_token"], job.get("text", "")
        mode = "default"
        try:
            if user_id in CLIMB_USER_IDS and text.strip() == "/climb":
                _climb_flag(user_id).touch()
                line_io.reply_text(reply_token, "🧗 已進入攀岩模式（傳 /exit 離開，3 小時沒互動自動離開）。")
                continue

            if user_id in CLIMB_USER_IDS and text.strip() == "/exit":
                _climb_flag(user_id).unlink(missing_ok=True)
                line_io.reply_text(reply_token, "已離開攀岩模式。")
                continue

            if job.get("video_id"):
                _climb_flag(user_id).touch()

            mode = "climb" if _in_climb(user_id) else "default"

            if text.strip() == "/reset":
                runner.reset_session(user_id, mode)
                line_io.reply_text(reply_token, "已重置攀岩對話。" if mode == "climb" else "已重置對話。")
                continue

            if text.strip() == "/綁定日曆":
                url = oauth.build_auth_url(user_id)
                line_io.reply_text(reply_token, f"請點以下連結完成 Google 日曆授權：\n{url}")
                continue

            if text.strip() == "/usage":
                d = runner.user_dir(user_id)
                usage = reminders.get_usage(d)
                line_io.reply_text(
                    reply_token,
                    f"本月推播用量：{usage['count']} / {reminders.PUSH_MONTHLY_LIMIT}（{usage['month']}）",
                )
                continue

            if mode == "climb":
                _climb_flag(user_id).touch()  # refresh the idle timer
                try:
                    await asyncio.to_thread(line_io.show_loading, user_id)
                except Exception as e:
                    print(f"[loading] {e}")

            if job.get("video_id"):
                text = await asyncio.to_thread(_prepare_video, user_id, job["video_id"])
            elif job.get("image_id"):
                text = _image_prompt(user_id, job["image_id"], mode)

            reply = await runner.run_turn(user_id, text, mode)
            _send(user_id, reply_token, reply, mode)
        except Exception as e:
            try:
                _send(user_id, reply_token, f"發生錯誤：{e}", mode)
            except Exception as send_err:
                print(f"[send] {send_err}")
        finally:
            queue.task_done()


def _enqueue(user_id: str, job: dict) -> None:
    if user_id not in _queues:
        _queues[user_id] = asyncio.Queue()
        _workers[user_id] = asyncio.create_task(_worker(user_id, _queues[user_id]))
    _queues[user_id].put_nowait(job)


FAMILY_GROUP_ID = os.environ.get("FAMILY_GROUP_ID")

WELCOME_MESSAGE = """👋 嗨！我是 Bird Assistant，你的個人 LINE 小助理。

我可以幫你：
📅 行事曆 — 查詢、新增、修改、刪除行程（個人曆/家庭共用曆）
⏰ 提醒 — 設定未來時間點主動提醒你（或全家）
🧠 記憶 — 記住你告訴我的事情（偏好、習慣等），之後可以直接問我
🍱 飲食記錄 — 傳食物照片，我會幫你記錄

指令
- /綁定日曆 — 授權 Google 日曆（用行事曆功能前需先做這步）
- /reset — 重置對話
- /usage — 查看本月推播用量

直接跟我說話就行，像「明天下午三點提醒我開會」「我這週有什麼行程」都可以 😊"""


def _check_reminders() -> None:
    now = datetime.now(timezone.utc)
    for user_id in os.listdir(runner.DATA_DIR):
        d = runner.DATA_DIR / user_id
        if not d.is_dir():
            continue
        for r in reminders.due_reminders(d, now):
            target = r.get("target", "self")
            to = FAMILY_GROUP_ID if target == "family" and FAMILY_GROUP_ID else user_id
            if reminders.try_record_push(d):
                line_io.push_text(to, f"⏰ 提醒：{r['text']}")
            else:
                line_io.push_text(user_id, "⏰ 有提醒到期，但本月推播額度已用完。")


@app.on_event("startup")
async def _startup():
    scheduler.add_job(_check_reminders, "interval", seconds=60, id="check_reminders")
    scheduler.start()


@app.on_event("shutdown")
async def _shutdown():
    scheduler.shutdown(wait=False)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/oauth/callback")
async def oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse(f"<h1>授權失敗</h1><p>{error}</p>", status_code=400)
    if not code or not state:
        raise HTTPException(status_code=400, detail="missing code/state")

    try:
        state_data = oauth.decode_state(state)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid or expired state")

    line_user_id = state_data["user_id"]
    token_data = oauth.exchange_code(code, state_data["code_verifier"])
    oauth.save_token(line_user_id, token_data)
    line_io.push_text(line_user_id, "綁定完成 ✅ 之後可以請我幫你查詢/建立行事曆事件了。")

    return HTMLResponse("<h1>綁定完成 ✅</h1><p>可以關閉此頁面，回到 LINE 繼續使用。</p>")


@app.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    try:
        events = line_io.parser.parse(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=403, detail="Invalid signature")

    for event in events:
        if isinstance(event, FollowEvent):
            line_io.reply_text(event.reply_token, WELCOME_MESSAGE)
            continue
        if not isinstance(event, MessageEvent):
            continue
        if event.source.type != "user":
            if event.source.type == "group":
                print(f"[group] message from group_id={event.source.group_id}")
            continue
        user_id = event.source.user_id
        if not _is_allowed(user_id):
            print(f"[unauthorized] message from user_id={user_id}")
            continue

        if isinstance(event.message, TextMessageContent):
            _enqueue(user_id, {"reply_token": event.reply_token, "text": event.message.text})
        elif isinstance(event.message, ImageMessageContent):
            d = runner.user_dir(user_id)
            content = line_io.get_message_content(event.message.id)
            image_path = d / "inbox" / f"{event.message.id}.jpg"
            image_path.write_bytes(content)
            _enqueue(user_id, {"reply_token": event.reply_token, "image_id": event.message.id})
        elif isinstance(event.message, VideoMessageContent):
            if user_id not in CLIMB_USER_IDS:
                line_io.reply_text(event.reply_token, "目前不支援影片。")
            elif (event.message.duration or 0) > MAX_VIDEO_MS:
                line_io.reply_text(event.reply_token, "影片超過 60 秒，請剪到卡住的那一段再傳。")
            else:
                # download waits for LINE transcoding, so it runs in the worker, not here
                _enqueue(user_id, {"reply_token": event.reply_token, "video_id": event.message.id})

    return {"ok": True}
