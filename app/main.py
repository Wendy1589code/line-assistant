import asyncio
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import ImageMessageContent, MessageEvent, TextMessageContent

from . import line_io, oauth, reminders, runner

app = FastAPI()

scheduler = AsyncIOScheduler()

ALLOWED_USER_IDS = {
    u.strip() for u in os.environ.get("ALLOWED_USER_IDS", "").split(",") if u.strip()
}

# per-user serial queues so messages from the same user are processed in order
_queues: dict[str, asyncio.Queue] = {}
_workers: dict[str, asyncio.Task] = {}


def _is_allowed(user_id: str) -> bool:
    # if allowlist is empty, allow everyone (useful for first local test)
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


async def _worker(user_id: str, queue: asyncio.Queue) -> None:
    while True:
        reply_token, text = await queue.get()
        try:
            if text.strip() == "/reset":
                runner.reset_session(user_id)
                line_io.reply_text(reply_token, "已重置對話。")
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

            reply = await runner.run_turn(user_id, text)
            line_io.reply_text(reply_token, reply)
        except Exception as e:
            line_io.reply_text(reply_token, f"發生錯誤：{e}")
        finally:
            queue.task_done()


def _enqueue(user_id: str, reply_token: str, text: str) -> None:
    if user_id not in _queues:
        _queues[user_id] = asyncio.Queue()
        _workers[user_id] = asyncio.create_task(_worker(user_id, _queues[user_id]))
    _queues[user_id].put_nowait((reply_token, text))


def _check_reminders() -> None:
    now = datetime.now(timezone.utc)
    for user_id in os.listdir(runner.DATA_DIR):
        d = runner.DATA_DIR / user_id
        if not d.is_dir():
            continue
        for r in reminders.due_reminders(d, now):
            if reminders.try_record_push(d):
                line_io.push_text(user_id, f"⏰ 提醒：{r['text']}")
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
        if not isinstance(event, MessageEvent):
            continue
        if event.source.type != "user":
            continue
        user_id = event.source.user_id
        if not _is_allowed(user_id):
            print(f"[unauthorized] message from user_id={user_id}")
            continue

        if isinstance(event.message, TextMessageContent):
            _enqueue(user_id, event.reply_token, event.message.text)
        elif isinstance(event.message, ImageMessageContent):
            d = runner.user_dir(user_id)
            content = line_io.get_message_content(event.message.id)
            image_path = d / "inbox" / f"{event.message.id}.jpg"
            image_path.write_bytes(content)
            text = (
                f"[使用者傳送了一張圖片，路徑：inbox/{event.message.id}.jpg]\n"
                "請看這張圖片的內容，並依使用者目前的對話情境處理"
                "（例如：如果是食物照片，記錄到飲食日記）。"
            )
            _enqueue(user_id, event.reply_token, text)

    return {"ok": True}
