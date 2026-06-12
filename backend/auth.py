"""Username+password login with signed session tokens.

Users come from APP_USERS_B64 (base64 of the user spec) or, as a
fallback for direct env / local dev, APP_USERS. Either way the decoded
spec is comma- or newline-separated "username:bcrypt-hash" entries.
Base64 is used on the cloud path because bcrypt hashes contain '$',
which Docker Compose's ${VAR} interpolation would otherwise mangle.
Auth is active only when at least one user is configured; without any,
every request passes through, so local development needs no login. The
token signing key is derived from the raw user spec, so any change to
it invalidates all existing sessions.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

import bcrypt


def _load_users_raw() -> str:
    encoded = (os.getenv("APP_USERS_B64") or "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode().strip()
        except Exception:
            return ""
    return (os.getenv("APP_USERS") or "").strip()


APP_USERS_RAW = _load_users_raw()
SESSION_TTL_SECONDS = 30 * 24 * 3600

_SIGNING_KEY = hashlib.sha256(("lawagent-session:" + APP_USERS_RAW).encode()).digest()

# Compared against when a username is unknown so a failed login costs the same
# whether or not the user exists (no username-enumeration timing oracle).
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt())


def _parse_users(raw: str) -> dict[str, str]:
    """Maps username -> bcrypt hash. Entries are "username:$2b$..." lines."""
    users: dict[str, str] = {}
    for entry in raw.replace("\n", ",").split(","):
        username, _, password_hash = entry.strip().partition(":")
        if username.strip() and password_hash:
            users[username.strip().lower()] = password_hash
    return users


_USERS = _parse_users(APP_USERS_RAW)


def auth_required() -> bool:
    return bool(_USERS)


def verify_credentials(username: str, password: str) -> bool:
    stored = _USERS.get(username.strip().lower())
    target = stored.encode() if stored else _DUMMY_HASH
    try:
        matched = bcrypt.checkpw(password.encode(), target)
    except ValueError:
        matched = False
    return bool(stored) and matched


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
