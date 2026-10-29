import json
import os
import shutil
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient

from . import calendar_mcp, climb_mcp, reminder_mcp, video

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "users"
GLOBAL_PROMPT = (ROOT / "prompts" / "CLAUDE.global.md").read_text(encoding="utf-8")
CLIMB_PROMPT = (ROOT / "prompts" / "CLAUDE.climb.md").read_text(encoding="utf-8")


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


def climb_video_prompt(user_id: str, video_id: str) -> str:
    """Frame a downloaded inbox/<video_id>.mp4 into 8 stills and describe them for the climb agent."""
    d = user_dir(user_id)
    src = d / "inbox" / f"{video_id}.mp4"
    frames = video.extract_frames(src, d / "inbox" / video_id)
    listing = "\n".join(str(f) for f in frames)
    return (
        f"[使用者傳了一段攀岩影片，長 {video.duration(src):.1f} 秒，video_id={video_id}。"
        f"已均勻抽 {len(frames)} 格（檔名含秒數）：\n{listing}]\n"
        "請用 Read 看這些影格，依目前對話情境分析動作。"
    )


def _session_file(d: Path, mode: str = "default") -> Path:
    return d / ("session.json" if mode == "default" else f"session.{mode}.json")


def _load_session_id(d: Path, mode: str) -> str | None:
    f = _session_file(d, mode)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8")).get("session_id")
        except Exception:
            return None
    return None


def _save_session_id(d: Path, mode: str, session_id: str) -> None:
    _session_file(d, mode).write_text(json.dumps({"session_id": session_id}), encoding="utf-8")


def reset_session(user_id: str, mode: str = "default") -> None:
    f = _session_file(user_dir(user_id), mode)
    if f.exists():
        f.unlink()


def _log_usage(user_id: str, message: object) -> None:
    """Print token usage + prompt-cache hit stats for one turn.

    The Agent SDK caches the system prompt / tools / history prefix automatically,
    so cache_read_input_tokens being non-zero from the 2nd turn on confirms it's working.
    """
    usage = getattr(message, "usage", None) or {}
    fresh = usage.get("input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_write = usage.get("cache_creation_input_tokens", 0)
    out = usage.get("output_tokens", 0)
    cost = getattr(message, "total_cost_usd", None)

    prompt_total = fresh + cache_read + cache_write
    hit = f"{cache_read / prompt_total * 100:.0f}%" if prompt_total else "n/a"
    # total_cost_usd is the running total of the (resumed) session, not this turn
    cost_str = f" session_cost=${cost:.4f}" if isinstance(cost, (int, float)) else ""
    print(
        f"[usage] user={user_id} cache_hit={hit} "
        f"(read={cache_read} write={cache_write} fresh={fresh}) out={out}{cost_str}"
    )


def _options(d: Path, user_id: str, mode: str, session_id: str | None) -> ClaudeAgentOptions:
    if mode == "climb":
        # read-only for now: no Bash/Edit, repo access only through the climb MCP
        return ClaudeAgentOptions(
            cwd=str(climb_mcp.REPO_DIR),
            model=os.environ.get("CLIMB_MODEL") or os.environ.get("MODEL"),
            system_prompt=CLIMB_PROMPT,
            resume=session_id,
            permission_mode="bypassPermissions",
            tools=["Read", "Glob", "Grep"],
            # don't load the repo's CLAUDE.md / skills / user settings: ~28k tokens per call we don't need
            setting_sources=[],
            mcp_servers={"climb": climb_mcp.build_server(d)},
        )
    return ClaudeAgentOptions(
        cwd=str(d),
        model=os.environ.get("MODEL"),
        system_prompt=GLOBAL_PROMPT,
        resume=session_id,
        permission_mode="bypassPermissions",
        mcp_servers={
            "calendar": calendar_mcp.build_server(d, user_id),
            "reminder": reminder_mcp.build_server(d),
        },
    )


async def _query(d: Path, user_id: str, text: str, session_id: str | None, mode: str) -> tuple[str, str | None]:
    options = _options(d, user_id, mode, session_id)

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
                _log_usage(user_id, message)
                if getattr(message, "is_error", False):
                    error = RuntimeError(getattr(message, "result", "unknown error"))

    if error:
        raise error

    return "\n".join(reply_parts).strip(), new_session_id


async def run_turn(user_id: str, text: str, mode: str = "default") -> str:
    """Send one message to this user's agent session (per mode) and return the reply text."""
    d = user_dir(user_id)
    session_id = _load_session_id(d, mode)

    try:
        reply, new_session_id = await _query(d, user_id, text, session_id, mode)
    except Exception:
        if session_id is None:
            raise
        # resume failed (e.g. transcript not found) -> retry with a fresh session
        reply, new_session_id = await _query(d, user_id, text, None, mode)

    if new_session_id:
        _save_session_id(d, mode, new_session_id)

    return reply or "（沒有產生回覆）"
