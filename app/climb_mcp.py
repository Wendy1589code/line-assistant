import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import video

ROOT = Path(__file__).resolve().parent.parent
REPO_DIR = Path(os.environ.get("CLIMB_REPO_DIR", ROOT / "data" / "climb_repo")).resolve()
# mb.py / kilter.py cache under ~/.cache; point HOME at a persistent dir under data/
CLIMB_HOME = Path(os.environ.get("CLIMB_HOME", ROOT / "data" / "climb_home")).resolve()
DEPLOY_KEY = os.environ.get("CLIMB_DEPLOY_KEY", str(ROOT / "secrets" / "climb_deploy_key"))
SKILL_DIR = REPO_DIR / ".claude" / "skills" / "moonboard-route"
PLAN_RE = re.compile(r"training-plan-(\d{4}-\d{2}-\d{2})-w\d+\.md$")


def _env() -> dict:
    known_hosts = CLIMB_HOME / ".ssh" / "known_hosts"
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    return {
        **os.environ,
        "HOME": str(CLIMB_HOME),
        "GIT_SSH_COMMAND": f"ssh -i {DEPLOY_KEY} -o IdentitiesOnly=yes "
        f"-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile={known_hosts}",
    }


def git(*args: str) -> str:
    r = subprocess.run(["git", "-C", str(REPO_DIR), *args], capture_output=True, text=True, env=_env(), timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失敗：{r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def find_plan(repo: Path, day: date) -> Path | None:
    """Weekly plan whose Monday-start covers `day` (raw/climbing/training-plan-<start>-wN.md)."""
    best = None
    for p in (repo / "raw" / "climbing").glob("training-plan-*-w*.md"):
        m = PLAN_RE.search(p.name)
        if not m:
            continue
        start = date.fromisoformat(m.group(1))
        if start <= day < start + timedelta(days=7) and (best is None or start > best[0]):
            best = (start, p)
    return best[1] if best else None


def day_section(text: str, day: date) -> str | None:
    """The `# Sat 10/31 — ...` block up to the next top-level heading."""
    head = re.compile(rf"^# [A-Z][a-z]{{2}} {day.month}/{day.day}\b.*$", re.M)
    m = head.search(text)
    if not m:
        return None
    nxt = re.compile(r"^# ", re.M).search(text, m.end())
    return text[m.start(): nxt.start() if nxt else len(text)].strip()


def _run_skill(script: str, *args: str) -> str:
    r = subprocess.run(
        [sys.executable, str(SKILL_DIR / script), *args],
        capture_output=True, text=True, env=_env(), cwd=str(REPO_DIR), timeout=120,
    )
    return (r.stdout + ("\n" + r.stderr if r.returncode else "")).strip() or "（沒有輸出）"


def _text(s: str, error: bool = False) -> dict:
    out = {"content": [{"type": "text", "text": s}]}
    if error:
        out["isError"] = True
    return out


def build_server(user_dir: Path):
    @tool(
        "today_plan",
        "先從 GitHub 拉最新的攀岩 repo，再回傳某一天的訓練計畫段落與檔案路徑。"
        " day 用 YYYY-MM-DD，留空 = 今天（Asia/Taipei）。",
        {"day": str},
    )
    async def today_plan(args):
        try:
            git("pull", "--ff-only", "-q")
        except RuntimeError as e:
            return _text(str(e), error=True)
        raw = (args.get("day") or "").strip()
        day = date.fromisoformat(raw) if raw else datetime.now(ZoneInfo("Asia/Taipei")).date()
        plan = find_plan(REPO_DIR, day)
        if not plan:
            return _text(f"找不到涵蓋 {day} 的週計畫檔（raw/climbing/training-plan-*-wN.md）", error=True)
        section = day_section(plan.read_text(encoding="utf-8"), day)
        rel = plan.relative_to(REPO_DIR)
        if not section:
            return _text(f"{rel} 裡沒有 {day.month}/{day.day} 的段落；需要的話用 Read 讀整份。")
        return _text(f"檔案：{rel}\n\n{section}")

    @tool("lookup_moonboard", "查 MoonBoard 2024 40° 的線（mb.py lookup）。names 用逗號分隔多條線名。", {"names": str})
    async def lookup_moonboard(args):
        names = [n.strip() for n in args["names"].split(",") if n.strip()]
        return _text(_run_skill("mb.py", "lookup", *names))

    @tool("lookup_kilter", "查 Climb Central Funan Kilter 45° 的線（kilter.py lookup）。names 用逗號分隔。", {"names": str})
    async def lookup_kilter(args):
        names = [n.strip() for n in args["names"].split(",") if n.strip()]
        return _text(_run_skill("kilter.py", "lookup", *names))

    @tool(
        "extract_frames",
        "從使用者傳的影片某一段再抽格（放大看卡點）。video_id 是影片訊息 id；start/end 秒數；n ≤ 12。",
        {"video_id": str, "start": float, "end": float, "n": int},
    )
    async def extract_frames(args):
        vid = re.sub(r"\D", "", args["video_id"])
        src = user_dir / "inbox" / f"{vid}.mp4"
        if not vid or not src.exists():
            return _text(f"找不到影片 {args['video_id']}", error=True)
        n = max(1, min(int(args.get("n") or 8), 12))
        start, end = float(args["start"]), float(args["end"])
        try:
            frames = video.extract_frames(src, user_dir / "inbox" / vid / f"zoom_{start:g}-{end:g}", n, start, end)
        except (ValueError, subprocess.SubprocessError) as e:
            return _text(f"抽格失敗：{e}", error=True)
        return _text("\n".join(str(f) for f in frames))

    return create_sdk_mcp_server(
        name="climb", version="1.0.0",
        tools=[today_plan, lookup_moonboard, lookup_kilter, extract_frames],
    )


if __name__ == "__main__":
    kb = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "workdir" / "llm_knowledge_base"
    plan = find_plan(kb, date(2026, 10, 31))
    assert plan and plan.name == "training-plan-2026-10-26-w10.md", plan
    sec = day_section(plan.read_text(encoding="utf-8"), date(2026, 10, 31))
    assert sec.startswith("# Sat 10/31") and "場中升級閘門" in sec and "# Sun 11/1" not in sec
    assert find_plan(kb, date(2026, 11, 2)).name == "training-plan-2026-11-02-w11.md"
    assert day_section("# Mon 10/26 — a\nx\n# Tue 10/27\n", date(2026, 10, 3)) is None
    print("climb_mcp.py ok")
