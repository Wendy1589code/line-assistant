import asyncio

from dotenv import load_dotenv

load_dotenv()

from . import runner

TEST_USER_ID = "local-cli-user"


async def main():
    print("本機對話 harness。輸入 /reset 重置對話，Ctrl+C 結束。\n")
    while True:
        try:
            text = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/reset":
            runner.reset_session(TEST_USER_ID)
            print("已重置對話。\n")
            continue

        reply = await runner.run_turn(TEST_USER_ID, text)
        print(f"助理: {reply}\n")


if __name__ == "__main__":
    asyncio.run(main())
