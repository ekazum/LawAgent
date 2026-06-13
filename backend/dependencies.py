"""Request-scoped helpers used by the route handlers in app.py."""

import os
from typing import Optional

from fastapi import HTTPException, Request

import auth

RATE_LIMIT_DETAIL = "יותר מדי ניסיונות התחברות. נסו שוב בעוד מספר דקות."


def current_user(request: Request) -> str:
    """The logged-in username, used to scope per-user data (conversations).

    When auth is disabled (no APP_USERS, e.g. local dev) everything shares a
    single "local" owner. Otherwise the require_session middleware has already
    rejected invalid tokens, so verify_token returns the real username here.
    """
    if not auth.auth_required():
        return "local"
    return auth.verify_token(request.headers.get("X-Session-Token", "")) or "local"


def resolve_api_key(x_api_key: Optional[str]) -> str:
    api_key = (x_api_key or os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        raise HTTPException(
            status_code=401,
            detail=(
                "לא הוגדר מפתח API של Anthropic. הגדר את משתנה הסביבה "
                "ANTHROPIC_API_KEY בשרת או הזן מפתח בממשק."
            ),
        )
    return api_key


def client_ip(request: Request) -> str:
    # Caddy appends the real peer to the right of X-Forwarded-For, so the
    # rightmost entry is trustworthy (a client can prepend fakes but not
    # forge the proxy-added value). Falls back to the socket peer locally.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
