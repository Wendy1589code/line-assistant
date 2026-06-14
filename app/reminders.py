import json
import os
from datetime import datetime, timezone
from pathlib import Path

PUSH_MONTHLY_LIMIT = int(os.environ.get("PUSH_MONTHLY_LIMIT", "450"))


def _reminders_file(user_dir: Path) -> Path:
    return user_dir / "reminders.json"


def _usage_file(user_dir: Path) -> Path:
    return user_dir / "push_usage.json"


def _load(f: Path, default):
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def _save(f: Path, data) -> None:
    f.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_reminders(user_dir: Path) -> list[dict]:
    return _load(_reminders_file(user_dir), [])


def add_reminder(user_dir: Path, remind_at: str, text: str, target: str = "self") -> dict:
    """remind_at: RFC3339 datetime string. target: 'self' or 'family'."""
    reminders = list_reminders(user_dir)
    new_id = (max((r["id"] for r in reminders), default=0)) + 1
    reminder = {"id": new_id, "remind_at": remind_at, "text": text, "fired": False, "target": target}
    reminders.append(reminder)
    _save(_reminders_file(user_dir), reminders)
    return reminder


def cancel_reminder(user_dir: Path, reminder_id: int) -> bool:
    reminders = list_reminders(user_dir)
    new_list = [r for r in reminders if r["id"] != reminder_id]
    if len(new_list) == len(reminders):
        return False
    _save(_reminders_file(user_dir), new_list)
    return True


def due_reminders(user_dir: Path, now: datetime) -> list[dict]:
    reminders = list_reminders(user_dir)
    due = []
    changed = False
    for r in reminders:
        if r["fired"]:
            continue
        try:
            remind_at = datetime.fromisoformat(r["remind_at"])
        except ValueError:
            continue
        if remind_at.tzinfo is None:
            remind_at = remind_at.replace(tzinfo=timezone.utc)
        if remind_at <= now:
            due.append(r)
            r["fired"] = True
            changed = True
    if changed:
        _save(_reminders_file(user_dir), reminders)
    return due


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_usage(user_dir: Path) -> dict:
    data = _load(_usage_file(user_dir), {"month": _current_month(), "count": 0})
    if data.get("month") != _current_month():
        data = {"month": _current_month(), "count": 0}
        _save(_usage_file(user_dir), data)
    return data


def try_record_push(user_dir: Path) -> bool:
    """Returns True if push is within quota and was recorded, False if quota exceeded."""
    data = get_usage(user_dir)
    if data["count"] >= PUSH_MONTHLY_LIMIT:
        return False
    data["count"] += 1
    _save(_usage_file(user_dir), data)
    return True
