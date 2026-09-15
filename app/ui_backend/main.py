"""FastAPI application entry point.

Wires the middleware, routers, the recording WebSocket and — in production —
the built React UI, so one port serves the whole app. Run with uvicorn
(see ``deploy/docker-entrypoint.sh`` or ``start.sh``).
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import settings_store
from auth import AuthMiddleware
from cleanup import start_cleanup_background_task
from config import get_settings
from routes import (
    admin_router,
    auth_router,
    drive_router,
    history_router,
    sessions_router,
    settings_router,
)
from websocket_handler import handle_websocket

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: apply saved settings overrides and start the retention cleanup loop."""
    logger.info("Starting up...")
    if not settings.secret_key:
        logger.warning("SECRET_KEY is not set — logins will not survive a restart. Set it in .env.")
    settings_store.apply_persisted_overrides()
    start_cleanup_background_task()
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Lecture Notes API",
    description="AI-powered lecture transcription and note-taking",
    version="1.0.0",
    lifespan=lifespan,
)

# Outermost middleware: /api and /ws are unreachable without a login cookie.
app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(admin_router)
app.include_router(settings_router)
app.include_router(auth_router)
app.include_router(history_router)
app.include_router(drive_router)


@app.websocket("/ws/session/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Recording channel: the browser streams audio chunks in, transcript
    and notes updates stream out. Requires a login cookie (enforced by
    ``AuthMiddleware``)."""
    await handle_websocket(websocket, session_id)


@app.get("/health")
async def health():
    """Liveness probe; the only path that needs no login."""
    return {"status": "healthy"}


# ── Built frontend ────────────────────────────────────────────────────────────
# In production the backend serves `app/ui_frontend/dist` itself, so one port carries the
# UI, the API and the websocket — a single tunnel or reverse proxy exposes the
# whole app, and there is no cross-origin traffic to configure. In development
# the Vite dev server proxies to us instead and `dist/` may not exist.
UI_DIST = Path(__file__).resolve().parent.parent / "ui_frontend" / "dist"

if (UI_DIST / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST / "assets"), name="ui-assets")

    def _privacy_page(path: Path) -> str:
        """privacy.html with the operator's contact substituted in."""
        email = get_settings().support_email.strip()
        contact = (
            f'<a href="mailto:{email}">{email}</a> — the operator of this installation'
            if email
            else "the operator of this installation — the support email shown on the Google "
            "sign-in screen, or the person who created your account"
        )
        return path.read_text().replace("{{CONTACT}}", contact)

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_ui(path: str):
        """Serve the single-page app and its static files."""
        # Real files (favicons, logo, manifest) are served as-is; anything else
        # falls through to index.html so client-side routes and reloads work.
        # The privacy page (linked from Google's consent screen, so it may be
        # requested with or without the extension) gets the operator's contact
        # address filled in from settings.
        if path in ("privacy", "privacy.html"):
            return HTMLResponse(_privacy_page(UI_DIST / "privacy.html"))
        candidate = (UI_DIST / path).resolve()
        if path and candidate.is_relative_to(UI_DIST) and candidate.is_file():
            return FileResponse(candidate)
        # index.html must never be cached: it names the hashed JS/CSS bundles,
        # and a stale copy keeps showing the previous release after a deploy.
        return FileResponse(
            UI_DIST / "index.html", headers={"Cache-Control": "no-cache, must-revalidate"}
        )

    logger.info("Serving built UI from %s", UI_DIST)
else:

    @app.get("/")
    async def root():
        """Placeholder when the UI has not been built (development)."""
        return {
            "message": "Lecture Notes API",
            "docs": "/docs",
            "hint": "Run `npm run build` in app/ui_frontend to serve the UI from this port.",
        }
