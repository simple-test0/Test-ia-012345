"""Optional shared-token auth.

When `settings.api_token` is set, REST requests must send the token in the
`X-API-Token` header and WebSocket clients must pass it as a `?token=` query
parameter. When it is empty (default), auth is disabled so the local dev
experience stays friction-free.

Because the REST check relies on a custom header (not cookies), it is not
exploitable via CSRF: a cross-origin page cannot set custom headers without a
CORS pre-flight that this app does not grant to untrusted origins.
"""
from fastapi import Header, HTTPException, status

from core.config import settings


async def require_api_token(x_api_token: str = Header(default="")) -> None:
    if not settings.api_token:
        return
    if x_api_token != settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )


def ws_token_ok(token: str) -> bool:
    """Validate a WebSocket token query parameter."""
    if not settings.api_token:
        return True
    return token == settings.api_token
