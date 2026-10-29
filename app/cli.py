import asyncio
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from . import runner

TEST_USER_ID = "local-cli-user"


async def main():
    # `python -m app.cli climb` = 攀岩模式；`/video <path>` 模擬從 LINE 傳影片
    mode = sys.argv[1] if len(sys.argv) > 1 else "default"
    print(f"本機對話 harness（{mode}）。輸入 /reset 重置對話，Ctrl+C 結束。\n")
    while True:
        try:
            text = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/reset":
            runner.reset_session(TEST_USER_ID, mode)
            print("已重置對話。\n")
            continue

        if mode == "climb" and text.startswith("/video "):
            src = Path(text.split(maxsplit=1)[1]).expanduser()
            video_id = str(abs(hash(src.name)))
            shutil.copy(src, runner.user_dir(TEST_USER_ID) / "inbox" / f"{video_id}.mp4")
            text = runner.climb_video_prompt(TEST_USER_ID, video_id)

        reply = await runner.run_turn(TEST_USER_ID, text, mode)
        print(f"助理: {reply}\n")


if __name__ == "__main__":
    asyncio.run(main())
