"""Shared-password login with signed session tokens.

Active only when APP_PASSWORD is set (cloud); without it every request
passes through, so local development needs no login. The token signing
key is derived from the password, so changing the password invalidates
all existing sessions.
"""

import base64
import hashlib
import hmac
import json
import os
import time

APP_PASSWORD = (os.getenv("APP_PASSWORD") or "").strip()
SESSION_TTL_SECONDS = 30 * 24 * 3600

_SIGNING_KEY = hashlib.sha256(("lawagent-session:" + APP_PASSWORD).encode()).digest()


def password_configured() -> bool:
    return bool(APP_PASSWORD)


def verify_password(password: str) -> bool:
    return password_configured() and hmac.compare_digest(password, APP_PASSWORD)


def issue_token() -> str:
    payload = json.dumps({"exp": int(time.time()) + SESSION_TTL_SECONDS}).encode()
    signature = hmac.new(_SIGNING_KEY, payload, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(payload).decode()
        + "."
        + base64.urlsafe_b64encode(signature).decode()
    )


# noinspection PyBroadException
def verify_token(token: str) -> bool:
    try:
        payload_b64, signature_b64 = token.split(".")
        payload = base64.urlsafe_b64decode(payload_b64)
        signature = base64.urlsafe_b64decode(signature_b64)
        expected = hmac.new(_SIGNING_KEY, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, signature):
            return False
        return json.loads(payload)["exp"] > time.time()
    except Exception:
        return False
