"""User accounts and the login cookie.

Passwords are bcrypt hashes in the ``users`` table. A successful login sets an
httpOnly cookie carrying ``<user id>:<expiry>:<hmac>`` signed with SECRET_KEY —
no server-side session store, so a restart does not log anyone out (as long as
SECRET_KEY is set in .env). The user row is re-read on every request so a
disabled or deleted account loses access immediately rather than at expiry.

Browsers send cookies on the same-origin WebSocket handshake too, so one login
covers the UI, the API and the recording socket.
"""

import base64
import hashlib
import hmac
import logging
import secrets
import socket
import time
import uuid
from dataclasses import dataclass, replace
from functools import lru_cache

import bcrypt
from fastapi import Depends, HTTPException, Request, WebSocket
from sqlalchemy import select

from core.config import get_settings
from core.database import AsyncSessionLocal
from core.models import User

logger = logging.getLogger(__name__)

COOKIE_NAME = "ln_session"

# Reachable without a login: liveness, the login endpoint itself, and the UI
# bundle (it holds no data; the app shows its login screen when /me says 401).
_OPEN_API_PATHS = {
    "/health",
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/status",
    "/api/auth/forgot",
    "/api/auth/reset",
    "/api/auth/verify",
    "/api/auth/verify/resend",
    "/api/auth/demo",
}


@dataclass(frozen=True)
class CurrentUser:
    """The signed-in user as seen by request handlers (resolved from the cookie)."""

    id: uuid.UUID
    username: str
    is_admin: bool
    is_demo: bool = False
    # The demo account reached through the tunnel (settings.demo_full_access_via_tunnel):
    # it may record, upload and edit, but still not share, use Drive or change the account.
    demo_full: bool = False

    @property
    def demo_read_only(self) -> bool:
        """The demo account anywhere it has not been given full access."""
        return self.is_demo and not self.demo_full


# ── Passwords ─────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Return a bcrypt hash (with a fresh salt) for storing in ``users.password_hash``."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time check of a plaintext password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# ── Signed cookie ─────────────────────────────────────────────────────────────

_runtime_key: str | None = None


def _secret() -> bytes:
    global _runtime_key
    key = get_settings().secret_key
    if not key:
        if _runtime_key is None:
            _runtime_key = secrets.token_urlsafe(32)
        key = _runtime_key
    return key.encode()


def _sign(payload: str) -> str:
    digest = hmac.new(_secret(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def make_token(user_id: uuid.UUID) -> str:
    """Build a signed login token ``<user id>:<expiry>:<hmac>`` valid for ``session_days``."""
    expires = int(time.time()) + get_settings().session_days * 86400
    payload = f"{user_id}:{expires}"
    return f"{payload}:{_sign(payload)}"


def parse_token(token: str) -> uuid.UUID | None:
    """Return the user id from a token, or ``None`` if the signature or expiry is bad."""
    try:
        user_id, expires, signature = token.rsplit(":", 2)
        payload = f"{user_id}:{expires}"
        if not hmac.compare_digest(signature, _sign(payload)):
            return None
        if int(expires) < time.time():
            return None
        return uuid.UUID(user_id)
    except (ValueError, TypeError):
        return None


def _cookie_from_headers(headers) -> str | None:
    for name, value in headers:
        if name.lower() != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE_NAME:
                return v
    return None


async def _load_user(user_id: uuid.UUID) -> CurrentUser | None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id, User.disabled.is_(False)))
        user = result.scalar_one_or_none()
    if user is None:
        return None
    return CurrentUser(
        id=user.id, username=user.username, is_admin=user.is_admin, is_demo=user.is_demo
    )


# ── The optional Cloudflare tunnel ────────────────────────────────────────────


@lru_cache(maxsize=1)
def _own_address() -> str | None:
    """This network namespace's own (non-loopback) IPv4 address.

    Funnel and uvicorn's trusted proxies connect over 127.0.0.1. The tunnel is
    configured to dial the container's own address instead, so a request whose
    immediate peer is that address can only have come through the tunnel.
    Found by asking the kernel which source address it would use to reach the
    outside (a UDP "connect" sends nothing).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: never actually contacted
            addr = s.getsockname()[0]
    except OSError:
        return None
    return None if addr.startswith("127.") else addr


def _header(scope, name: bytes) -> str | None:
    for k, v in scope.get("headers", []):
        if k == name:
            return v.decode("latin-1")
    return None


def _mark_tunnel_request(scope) -> bool:
    """If this request came through the tunnel, say so and apply its proxy headers.

    uvicorn only honours X-Forwarded-* from 127.0.0.1, so for the tunnel's own
    address it left the client as the tunnel and the scheme as plain http:
    restore the visitor's address (right-most X-Forwarded-For, the one the
    tunnel added) and the scheme, so rate limits and Secure cookies still work.
    """
    if not get_settings().demo_full_access_via_tunnel:
        return False
    client = scope.get("client")
    own = _own_address()
    if not client or not own or client[0] != own:
        return False
    forwarded = _header(scope, b"x-forwarded-for")
    if forwarded:
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if hops:
            scope["client"] = (hops[-1], 0)
    if (_header(scope, b"x-forwarded-proto") or "").lower() == "https":
        scope["scheme"] = "wss" if scope["type"] == "websocket" else "https"
    return True


def request_via_tunnel(request: Request) -> bool:
    """Whether the middleware saw this request arrive through the tunnel."""
    return bool(request.scope.get("state", {}).get("via_tunnel"))


# ── Middleware ────────────────────────────────────────────────────────────────


class AuthMiddleware:
    """Pure ASGI so it covers both HTTP and WebSocket scopes.

    Resolves the cookie to ``scope["state"]["user"]`` and rejects protected
    paths (/api/*, /ws/*) without one. Static UI paths pass through.
    """

    def __init__(self, app):
        """Wrap the downstream ASGI app."""
        self.app = app

    async def __call__(self, scope, receive, send):
        """Resolve the cookie, then admit or reject the request/handshake."""
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        via_tunnel = _mark_tunnel_request(scope)
        path = scope["path"]
        protected = path.startswith("/api/") or path.startswith("/ws/")
        if path in _OPEN_API_PATHS:
            protected = False

        user = None
        token = _cookie_from_headers(scope.get("headers", []))
        if token:
            user_id = parse_token(token)
            if user_id:
                user = await _load_user(user_id)
        if user is not None and user.is_demo and via_tunnel:
            user = replace(user, demo_full=True)
        state = scope.setdefault("state", {})
        state["user"] = user
        state["via_tunnel"] = via_tunnel

        if protected and user is None:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
                return
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"detail":"Not signed in"}'})
            return

        await self.app(scope, receive, send)


# ── Dependencies ──────────────────────────────────────────────────────────────


def current_user(request: Request) -> CurrentUser:
    """FastAPI dependency: the signed-in user, or 401."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def forbid_demo(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """FastAPI dependency: the signed-in user unless it is the demo account (403).

    For what the demo may never do, even with full access: share lectures,
    use Google Drive, or change the (shared) account itself."""
    if user.is_demo:
        raise HTTPException(
            status_code=403,
            detail="The demo account can't do that — create your own account for it",
        )
    return user


def forbid_read_only_demo(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """FastAPI dependency: refuse the demo account where it is read-only (403).

    For recording, uploads and edits: allowed for the demo only with full
    access (see ``CurrentUser.demo_full``)."""
    if user.demo_read_only:
        raise HTTPException(
            status_code=403,
            detail="The demo is read-only here — create your own account to record lectures",
        )
    return user


def require_admin(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """FastAPI dependency: the signed-in user if they are an admin, else 403."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def websocket_user(websocket: WebSocket) -> CurrentUser | None:
    """The signed-in user for a WebSocket connection (set by the middleware), or ``None``."""
    return websocket.scope.get("state", {}).get("user")


def set_login_cookie(response, request: Request, user_id: uuid.UUID) -> None:
    """Attach a fresh login cookie for ``user_id`` to ``response``."""
    # Secure only over https: a Secure cookie is dropped on plain-http localhost.
    response.set_cookie(
        COOKIE_NAME,
        make_token(user_id),
        max_age=get_settings().session_days * 86400,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


def clear_login_cookie(response) -> None:
    """Remove the login cookie (sign out)."""
    response.delete_cookie(COOKIE_NAME, path="/")
