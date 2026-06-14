import json
import os
import shutil
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from . import calendar_mcp, reminder_mcp

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "users"
GLOBAL_PROMPT = (ROOT / "prompts" / "CLAUDE.global.md").read_text(encoding="utf-8")


def user_dir(user_id: str) -> Path:
    d = DATA_DIR / user_id
    (d / "memory").mkdir(parents=True, exist_ok=True)
    (d / "inbox").mkdir(parents=True, exist_ok=True)

    claude_md = d / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(
            "# 個人化設定\n\n（這裡可以放這位使用者的稱呼、偏好等）\n", encoding="utf-8"
        )

    memory_index = d / "memory" / "MEMORY.md"
    if not memory_index.exists():
        memory_index.write_text("# 記憶索引\n\n（目前沒有記憶）\n", encoding="utf-8")

    return d


def _session_file(d: Path) -> Path:
    return d / "session.json"


def _load_session_id(d: Path) -> str | None:
    f = _session_file(d)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("session_id")
        except Exception:
            return None
    return None


def _save_session_id(d: Path, session_id: str) -> None:
    _session_file(d).write_text(json.dumps({"session_id": session_id}), encoding="utf-8")


def reset_session(user_id: str) -> None:
    f = _session_file(user_dir(user_id))
    if f.exists():
        f.unlink()


async def _query(d: Path, text: str, session_id: str | None) -> tuple[str, str | None]:
    options = ClaudeAgentOptions(
        cwd=str(d),
        model=os.environ.get("MODEL"),
        system_prompt=GLOBAL_PROMPT,
        resume=session_id,
        permission_mode="bypassPermissions",
        mcp_servers={
            "calendar": calendar_mcp.build_server(d),
            "reminder": reminder_mcp.build_server(d),
        },
    )

    reply_parts: list[str] = []
    new_session_id = session_id
    error: Exception | None = None

    async with ClaudeSDKClient(options=options) as client:
        await client.query(text)
        async for message in client.receive_response():
            msg_type = type(message).__name__
            if msg_type == "AssistantMessage":
                for block in getattr(message, "content", []):
                    if type(block).__name__ == "TextBlock":
                        reply_parts.append(block.text)
            elif msg_type == "ResultMessage":
                new_session_id = getattr(message, "session_id", new_session_id)
                if getattr(message, "is_error", False):
                    error = RuntimeError(getattr(message, "result", "unknown error"))

    if error:
        raise error

    return "\n".join(reply_parts).strip(), new_session_id


async def run_turn(user_id: str, text: str) -> str:
    """Send one message to this user's agent session and return the reply text."""
    d = user_dir(user_id)
    session_id = _load_session_id(d)

    try:
        reply, new_session_id = await _query(d, text, session_id)
    except Exception:
        if session_id is None:
            raise
        # resume failed (e.g. transcript not found) -> retry with a fresh session
        reply, new_session_id = await _query(d, text, None)

    if new_session_id:
        _save_session_id(d, new_session_id)

    return reply or "（沒有產生回覆）"
