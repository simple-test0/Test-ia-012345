"""Optional shared-token auth.

When `settings.api_token` is set, REST requests must send the token in the
`X-API-Token` header and WebSocket clients must pass it as a `?token=` query
parameter. When it is empty (default), auth is disabled so the local dev
experience stays friction-free.

Because the REST check relies on a custom header (not cookies), it is not
exploitable via CSRF: a cross-origin page cannot set custom headers without a
CORS pre-flight that this app does not grant to untrusted origins.
"""
import hmac

from fastapi import Header, HTTPException, status

from core.config import settings


def _matches(candidate: str) -> bool:
    # Constant-time comparison: no timing side channel on the token.
    return hmac.compare_digest(candidate.encode(), settings.api_token.encode())


async def require_api_token(x_api_token: str = Header(default="")) -> None:
    if not settings.api_token:
        return
    if not _matches(x_api_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )


def ws_token_ok(token: str) -> bool:
    """Validate a WebSocket token query parameter."""
    if not settings.api_token:
        return True
    return _matches(token or "")


async def require_api_token_or_query(
    x_api_token: str = Header(default=""), token: str = ""
) -> None:
    """Same check, also accepting `?token=` — for URLs used directly by the
    browser (<img src>, download links) that cannot carry custom headers.
    Only used on read-only file routes."""
    if not settings.api_token:
        return
    if not (_matches(x_api_token) or _matches(token)):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
        )
