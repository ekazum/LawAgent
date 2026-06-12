"""Username+password login with signed session tokens.

Users come from the APP_USERS env var: comma- or newline-separated
"username:password" entries. Auth is active only when APP_USERS is set
(cloud); without it every request passes through, so local development
needs no login. The token signing key is derived from the raw user
spec, so any change to it invalidates all existing sessions.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

APP_USERS_RAW = (os.getenv("APP_USERS") or "").strip()
SESSION_TTL_SECONDS = 30 * 24 * 3600

_SIGNING_KEY = hashlib.sha256(("lawagent-session:" + APP_USERS_RAW).encode()).digest()


def _parse_users(raw: str) -> dict[str, str]:
    users: dict[str, str] = {}
    for entry in raw.replace("\n", ",").split(","):
        username, _, password = entry.strip().partition(":")
        if username.strip() and password:
            users[username.strip().lower()] = password
    return users


_USERS = _parse_users(APP_USERS_RAW)


def auth_required() -> bool:
    return bool(_USERS)


def verify_credentials(username: str, password: str) -> bool:
    expected = _USERS.get(username.strip().lower())
    return bool(expected) and hmac.compare_digest(password, expected)


def issue_token(username: str) -> str:
    payload = json.dumps(
        {
            "sub": username.strip().lower(),
            "exp": int(time.time()) + SESSION_TTL_SECONDS,
        }
    ).encode()
    signature = hmac.new(_SIGNING_KEY, payload, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(payload).decode()
        + "."
        + base64.urlsafe_b64encode(signature).decode()
    )


# noinspection PyBroadException
def verify_token(token: str) -> Optional[str]:
    """Returns the logged-in username, or None if the token is invalid."""
    try:
        payload_b64, signature_b64 = token.split(".")
        payload = base64.urlsafe_b64decode(payload_b64)
        signature = base64.urlsafe_b64decode(signature_b64)
        expected = hmac.new(_SIGNING_KEY, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature):
            return None
        data = json.loads(payload)
        if data["exp"] <= time.time() or data["sub"] not in _USERS:
            return None
        return data["sub"]
    except Exception:
        return None
