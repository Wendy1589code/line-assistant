import os

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    ReplyMessageRequest,
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
