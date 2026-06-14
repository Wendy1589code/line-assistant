from pathlib import Path

from claude_agent_sdk import create_sdk_mcp_server, tool

from . import reminders


def build_server(user_dir: Path):
    @tool(
        "set_reminder",
        "設定一個未來的提醒，到時間會主動發 LINE 訊息。"
        " remind_at 用 RFC3339 格式，例如 2026-06-15T20:00:00+08:00。"
        " target 預設 'self'（只提醒自己）；若使用者明確說「提醒全家/家人」，target 填 'family'（發到家庭群組）。",
        {"remind_at": str, "text": str, "target": str},
    )
    async def set_reminder(args):
        target = args.get("target") or "self"
        r = reminders.add_reminder(user_dir, args["remind_at"], args["text"], target)
        who = "全家" if target == "family" else "你"
        return {"content": [{"type": "text", "text": f"已設定提醒 #{r['id']}（{who}）：{r['remind_at']} - {r['text']}"}]}

    @tool(
        "list_reminders",
        "列出所有尚未觸發的提醒。",
        {},
    )
    async def list_reminders_tool(args):
        all_reminders = [r for r in reminders.list_reminders(user_dir) if not r["fired"]]
        return {"content": [{"type": "text", "text": str(all_reminders)}]}

    @tool(
        "cancel_reminder",
        "取消一個尚未觸發的提醒。reminder_id 來自 list_reminders 的結果。",
        {"reminder_id": int},
    )
    async def cancel_reminder_tool(args):
        ok = reminders.cancel_reminder(user_dir, args["reminder_id"])
        return {"content": [{"type": "text", "text": "已取消" if ok else "找不到該提醒"}]}

    return create_sdk_mcp_server(
        name="reminder",
        tools=[set_reminder, list_reminders_tool, cancel_reminder_tool],
    )
