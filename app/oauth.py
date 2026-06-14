import base64
import hashlib
import os
import secrets
from pathlib import Path

from google_auth_oauthlib.flow import Flow
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from .runner import user_dir

ROOT = Path(__file__).resolve().parent.parent
CLIENT_SECRET_FILE = os.environ["GOOGLE_CLIENT_SECRET_FILE"]
BASE_URL = os.environ["BASE_URL"]
REDIRECT_URI = f"{BASE_URL}/oauth/callback"

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]

_serializer = URLSafeTimedSerializer(os.environ["LINE_CHANNEL_SECRET"], salt="oauth-state")


def _flow() -> Flow:
    return Flow.from_client_secrets_file(
        CLIENT_SECRET_FILE, scopes=SCOPES, redirect_uri=REDIRECT_URI
    )


def build_auth_url(line_user_id: str) -> str:
    code_verifier = secrets.token_urlsafe(64)[:128]
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )

    state = _serializer.dumps({"user_id": line_user_id, "code_verifier": code_verifier})

    flow = _flow()
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )
    return auth_url


def decode_state(state: str, max_age: int = 600) -> dict:
    """Returns {"user_id": ..., "code_verifier": ...}, or raises ValueError."""
    try:
        return _serializer.loads(state, max_age=max_age)
    except (BadSignature, SignatureExpired) as e:
        raise ValueError("invalid or expired state") from e


def exchange_code(code: str, code_verifier: str) -> dict:
    flow = _flow()
    flow.code_verifier = code_verifier
    flow.fetch_token(code=code)
    creds = flow.credentials
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }


def save_token(line_user_id: str, token_data: dict) -> None:
    d = user_dir(line_user_id)
    import json
    (d / "google_token.json").write_text(json.dumps(token_data), encoding="utf-8")


def has_token(line_user_id: str) -> bool:
    return (user_dir(line_user_id) / "google_token.json").exists()
