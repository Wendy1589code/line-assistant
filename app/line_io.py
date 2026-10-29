import os
import time

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
    ShowLoadingAnimationRequest,
    PushMessageRequest,
    TextMessage,
)
from linebot.v3.webhook import WebhookParser

CHANNEL_SECRET = os.environ["LINE_CHANNEL_SECRET"]
CHANNEL_ACCESS_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]

_config = Configuration(access_token=CHANNEL_ACCESS_TOKEN)
parser = WebhookParser(CHANNEL_SECRET)


def _chunk_text(text: str, limit: int = 5000) -> list[str]:
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks or [""]


def reply_text(reply_token: str, text: str) -> None:
    messages = [TextMessage(text=t) for t in _chunk_text(text)[:5]]
    with ApiClient(_config) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=messages)
        )


def get_message_content(message_id: str) -> bytes:
    with ApiClient(_config) as api_client:
        return MessagingApiBlob(api_client).get_message_content(message_id)


def push_text(user_id: str, text: str) -> None:
    messages = [TextMessage(text=t) for t in _chunk_text(text)[:5]]
    with ApiClient(_config) as api_client:
        MessagingApi(api_client).push_message(
            PushMessageRequest(to=user_id, messages=messages)
        )


def show_loading(user_id: str, seconds: int = 60) -> None:
    """LINE's typing indicator; disappears when a reply/push arrives or after `seconds` (5-60, multiple of 5)."""
    with ApiClient(_config) as api_client:
        MessagingApi(api_client).show_loading_animation(
            ShowLoadingAnimationRequest(chat_id=user_id, loading_seconds=seconds)
        )


def get_video_content(message_id: str, timeout: float = 60) -> bytes:
    """User-sent videos are transcoded by LINE first; poll until ready, then download."""
    deadline = time.monotonic() + timeout
    with ApiClient(_config) as api_client:
        blob = MessagingApiBlob(api_client)
        while True:
            status = blob.get_message_content_transcoding_by_message_id(message_id).status
            if status == "succeeded":
                return blob.get_message_content(message_id)
            if status == "failed" or time.monotonic() > deadline:
                raise RuntimeError(f"LINE 影片轉檔{'失敗' if status == 'failed' else '逾時'}")
            time.sleep(2)
