"""Routers, one per area of the API."""

from .admin import router as admin_router
from .auth import router as auth_router
from .drive import router as drive_router
from .history import router as history_router
from .sessions import router as sessions_router
from .settings import router as settings_router

__all__ = [
    "sessions_router",
    "admin_router",
    "settings_router",
    "auth_router",
    "history_router",
    "drive_router",
]
