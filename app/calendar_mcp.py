from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import calendar_tools


def build_server(user_dir: Path, user_id: str | None = None):
    @tool(
        "list_events",
        "查詢指定時間範圍內的行事曆事件。calendar_id 用 'primary'（個人曆）或 'family'（家庭共用曆）。"
        " time_min/time_max 用 RFC3339 格式，例如 2026-06-15T00:00:00+08:00。",
        {"calendar_id": str, "time_min": str, "time_max": str},
    )
    async def list_events(args):
        try:
            events = calendar_tools.list_events(
                user_dir, args["calendar_id"], args["time_min"], args["time_max"], user_id
            )
        except calendar_tools.ForbiddenCalendarError as e:
            return {"content": [{"type": "text", "text": str(e)}], "isError": True}
        return {"content": [{"type": "text", "text": str(events)}]}

    @tool(
        "create_event",
        "在指定日曆建立一個事件。calendar_id 用 'primary'（個人曆）或 'family'（家庭共用曆）。"
        " start/end 用 RFC3339 格式，例如 2026-06-15T20:00:00+08:00。",
        {
            "calendar_id": str,
            "summary": str,
            "start": str,
            "end": str,
            "location": str,
            "description": str,
        },
    )
    async def create_event(args):
        result = calendar_tools.create_event(
            user_dir,
            args["calendar_id"],
            args["summary"],
            args["start"],
            args["end"],
            args.get("location") or None,
            args.get("description") or None,
        )
        return {"content": [{"type": "text", "text": str(result)}]}

    @tool(
        "update_event",
        "修改指定日曆中的事件。destructive：執行前必須先跟使用者確認。"
        " calendar_id 用 'primary' 或 'family'，event_id 來自 list_events 的結果。"
        " 只填要修改的欄位，其他留空。",
        {
            "calendar_id": str,
            "event_id": str,
            "summary": str,
            "start": str,
            "end": str,
            "location": str,
        },
    )
    async def update_event(args):
        result = calendar_tools.update_event(
            user_dir,
            args["calendar_id"],
            args["event_id"],
            args.get("summary") or None,
            args.get("start") or None,
            args.get("end") or None,
            args.get("location") or None,
        )
        return {"content": [{"type": "text", "text": str(result)}]}

    @tool(
        "delete_event",
        "刪除指定日曆中的事件。destructive：執行前必須先跟使用者確認。"
        " calendar_id 用 'primary' 或 'family'，event_id 來自 list_events 的結果。",
        {"calendar_id": str, "event_id": str},
    )
    async def delete_event(args):
        calendar_tools.delete_event(user_dir, args["calendar_id"], args["event_id"])
        return {"content": [{"type": "text", "text": "已刪除"}]}

    return create_sdk_mcp_server(
        name="calendar",
        tools=[list_events, create_event, update_event, delete_event],
    )
