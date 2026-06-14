import json
import os
from pathlib import Path

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

FAMILY_CALENDAR_ID = os.environ["FAMILY_CALENDAR_ID"]
ICLOUD_CALENDAR_ID = os.environ.get("ICLOUD_CALENDAR_ID")
YUNPEI_CALENDAR_ID = os.environ.get("YUNPEI_CALENDAR_ID")
YUNPEI_ALLOWED_USER_ID = os.environ.get("YUNPEI_ALLOWED_USER_ID")


class NotLinkedError(Exception):
    pass


def _token_file(user_dir: Path) -> Path:
    return user_dir / "google_token.json"


def _credentials(user_dir: Path) -> Credentials:
    f = _token_file(user_dir)
    if not f.exists():
        raise NotLinkedError("使用者尚未綁定 Google 日曆")

    data = json.loads(f.read_text(encoding="utf-8"))
    creds = Credentials(
        token=data["token"],
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleRequest())
        data["token"] = creds.token
        f.write_text(json.dumps(data), encoding="utf-8")

    return creds


def _service(user_dir: Path):
    return build("calendar", "v3", credentials=_credentials(user_dir), cache_discovery=False)


class ForbiddenCalendarError(Exception):
    pass


def _resolve_calendar_id(calendar_id: str, user_id: str | None = None) -> str:
    if calendar_id in ("family", "家庭", "家庭曆"):
        return FAMILY_CALENDAR_ID
    if calendar_id in ("icloud", "apple", "iCloud") and ICLOUD_CALENDAR_ID:
        return ICLOUD_CALENDAR_ID
    if calendar_id in ("yunpei", "主要", "主要行事曆") and YUNPEI_CALENDAR_ID:
        if YUNPEI_ALLOWED_USER_ID and user_id != YUNPEI_ALLOWED_USER_ID:
            raise ForbiddenCalendarError("沒有權限存取這本日曆")
        return YUNPEI_CALENDAR_ID
    return "primary"


def list_events(
    user_dir: Path, calendar_id: str, time_min: str, time_max: str, user_id: str | None = None
) -> list[dict]:
    svc = _service(user_dir)
    resp = (
        svc.events()
        .list(
            calendarId=_resolve_calendar_id(calendar_id, user_id),
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = []
    for item in resp.get("items", []):
        events.append(
            {
                "id": item["id"],
                "summary": item.get("summary", "(無標題)"),
                "start": item.get("start", {}),
                "end": item.get("end", {}),
                "location": item.get("location"),
                "htmlLink": item.get("htmlLink"),
            }
        )
    return events


def create_event(
    user_dir: Path,
    calendar_id: str,
    summary: str,
    start: str,
    end: str,
    location: str | None = None,
    description: str | None = None,
) -> dict:
    svc = _service(user_dir)
    body = {
        "summary": summary,
        "start": {"dateTime": start, "timeZone": os.environ.get("TZ", "Asia/Taipei")},
        "end": {"dateTime": end, "timeZone": os.environ.get("TZ", "Asia/Taipei")},
    }
    if location:
        body["location"] = location
    if description:
        body["description"] = description

    created = svc.events().insert(calendarId=_resolve_calendar_id(calendar_id), body=body).execute()
    return {"id": created["id"], "htmlLink": created.get("htmlLink")}


def update_event(
    user_dir: Path,
    calendar_id: str,
    event_id: str,
    summary: str | None = None,
    start: str | None = None,
    end: str | None = None,
    location: str | None = None,
) -> dict:
    svc = _service(user_dir)
    cal_id = _resolve_calendar_id(calendar_id)
    event = svc.events().get(calendarId=cal_id, eventId=event_id).execute()

    if summary is not None:
        event["summary"] = summary
    if location is not None:
        event["location"] = location
    if start is not None:
        event["start"] = {"dateTime": start, "timeZone": os.environ.get("TZ", "Asia/Taipei")}
    if end is not None:
        event["end"] = {"dateTime": end, "timeZone": os.environ.get("TZ", "Asia/Taipei")}

    updated = svc.events().update(calendarId=cal_id, eventId=event_id, body=event).execute()
    return {"id": updated["id"], "htmlLink": updated.get("htmlLink")}


def delete_event(user_dir: Path, calendar_id: str, event_id: str) -> None:
    svc = _service(user_dir)
    svc.events().delete(calendarId=_resolve_calendar_id(calendar_id), eventId=event_id).execute()
