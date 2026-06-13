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

SESSION_TTL_SECONDS = 30 * 24 * 3600


def _load_users_raw() -> str:
    encoded = (os.getenv("APP_USERS_B64") or "").strip()
    if encoded:
        try:
            return base64.b64decode(encoded).decode().strip()
        except Exception:
            return ""
    return (os.getenv("APP_USERS") or "").strip()


def _parse_users(raw: str) -> dict[str, str]:
    """Maps username -> bcrypt hash. Entries are "username:$2b$..." lines."""
    users: dict[str, str] = {}
    for entry in raw.replace("\n", ",").split(","):
        username, _, password_hash = entry.strip().partition(":")
        if username.strip() and password_hash:
            users[username.strip().lower()] = password_hash
    return users


class Authenticator:
    """Validates credentials and issues/verifies HMAC-signed session tokens.

    State (user table, signing key, dummy hash) is fixed at construction.
    A single instance (`authenticator`) is built from the environment at
    import; routes get it via get_authenticator, while the require_session
    middleware (outside FastAPI DI) uses the singleton directly.
    """

    def __init__(
        self,
        users: dict[str, str],
        signing_key: bytes,
        dummy_hash: bytes,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ) -> None:
        self._users = users
        self._signing_key = signing_key
        self._dummy_hash = dummy_hash
        self._ttl = ttl_seconds

    @classmethod
    def from_env(cls) -> "Authenticator":
        raw = _load_users_raw()
        signing_key = hashlib.sha256(("lawagent-session:" + raw).encode()).digest()
        # Compared against when a username is unknown so a failed login costs
        # the same whether or not the user exists (no enumeration timing oracle).
        dummy_hash = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt())
        return cls(_parse_users(raw), signing_key, dummy_hash)

    def auth_required(self) -> bool:
        return bool(self._users)

    def verify_credentials(self, username: str, password: str) -> bool:
        stored = self._users.get(username.strip().lower())
        target = stored.encode() if stored else self._dummy_hash
        try:
            matched = bcrypt.checkpw(password.encode(), target)
        except ValueError:
            matched = False
        return bool(stored) and matched

    def issue_token(self, username: str) -> str:
        payload = json.dumps(
            {
                "sub": username.strip().lower(),
                "exp": int(time.time()) + self._ttl,
            }
        ).encode()
        signature = hmac.new(self._signing_key, payload, hashlib.sha256).digest()
        return (
            base64.urlsafe_b64encode(payload).decode()
            + "."
            + base64.urlsafe_b64encode(signature).decode()
        )

    # noinspection PyBroadException
    def verify_token(self, token: str) -> Optional[str]:
        """Returns the logged-in username, or None if the token is invalid."""
        try:
            payload_b64, signature_b64 = token.split(".")
            payload = base64.urlsafe_b64decode(payload_b64)
            signature = base64.urlsafe_b64decode(signature_b64)
            expected = hmac.new(self._signing_key, payload, hashlib.sha256).digest()
            if not hmac.compare_digest(expected, signature):
                return None
            data = json.loads(payload)
            if data["exp"] <= time.time() or data["sub"] not in self._users:
                return None
            return data["sub"]
        except Exception:
            return None


# Process-wide singleton, built from the environment at import.
authenticator = Authenticator.from_env()


def get_authenticator() -> Authenticator:
    return authenticator
