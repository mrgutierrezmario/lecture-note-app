"""Application settings.

Values come from environment variables or ``STATE_DIR/.env`` (pydantic-settings),
with the defaults below. Some fields can also be changed at runtime from the
Settings panel; ``settings_store`` persists those and re-applies them on
startup. ``get_settings()`` returns one shared instance, so runtime changes
are visible everywhere immediately.
"""

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

# Where runtime-written files live: .env (API key saved from the Settings panel)
# and runtime_settings.json. Defaults to the backend directory; the Docker image
# points it at a mounted volume so those survive container recreation.
STATE_DIR = Path(os.environ.get("STATE_DIR", Path(__file__).resolve().parent))


class Settings(BaseSettings):
    """All tunables, grouped by concern. See ``.env.example`` for the env names."""

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/lecture_notes"

    # Whisper. "small" transcribes a 5s chunk in ~1.1s on CPU, so it keeps up
    # with the 5s recording cadence. large-v3 is far more accurate but runs
    # slower than realtime on CPU, so chunks queue up and lag grows without
    # bound over a lecture — only select it with a GPU or for offline reruns.
    whisper_model: str = "small"

    # Notes Generation
    notes_interval_seconds: int = 60
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3:latest"

    # S3/MinIO
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "lecture-audio"
    s3_region: str = "us-east-1"
    s3_secure: bool = False

    # Anthropic. vision_model reads lecture slides, diagrams and equations from
    # screenshots the student pastes into chat — the weakest vision tier struggles
    # with dense slides, so this defaults to the strongest rather than the cheapest.
    anthropic_api_key: Optional[str] = None
    vision_model: str = "claude-opus-5"

    # Notes + chat text generation: "ollama" (local, default), "gemini" or "openai".
    # Cloud providers fall back to Ollama on any failure. Keys are set from the
    # Settings panel and stored in STATE_DIR/.env.
    text_provider: str = "ollama"
    claude_text_model: str = "claude-sonnet-5"
    # Slides/images: "claude" (default), "gemini", "openai", or "llava" (local only).
    # Falls back to llava, then BLIP.
    vision_provider: str = "claude"
    gemini_api_key: Optional[str] = None
    gemini_model: str = "gemini-3.6-flash"
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"

    # Signs login cookies. Unset: a random key is generated at startup, which
    # logs everyone out on every restart — set it in .env for real use.
    secret_key: str = ""
    session_days: int = 30

    # Outgoing mail (password reset links). Gmail: address + App Password
    # (myaccount.google.com/apppasswords). Unset = "Forgot password?" is hidden.
    mail_username: str = ""
    mail_password: str = ""
    mail_from: str = ""
    mail_from_name: str = "AI Lecture Notes"
    # Optional: where replies go (e.g. a no-reply address). Blank = the From address.
    mail_reply_to: str = ""
    mail_server: str = "smtp.gmail.com"
    mail_port: int = 465
    # Base URL used in emailed links, e.g. https://notes.example.com
    public_url: str = ""
    # Shown on the privacy page as the operator's contact. Blank = generic wording.
    support_email: str = ""

    # Google OAuth client ("Web application" type) that lets users connect
    # their own Google Drive. Set from the Settings panel; the secret lives in
    # STATE_DIR/.env. Redirect URI to register: <public_url>/api/drive/callback
    google_client_id: str = ""
    google_client_secret: Optional[str] = None

    # Whether the sign-in page offers "Create account". Turn off once everyone
    # who should have an account has one.
    registration_open: bool = True

    # Largest document/image upload accepted (MB). Uploads are read into memory.
    max_upload_mb: int = 50

    # How many lectures a user may keep locked (exempt from the audio cleanup).
    max_locked_lectures: int = 5

    # Per-user cap on retained audio (MB). Admins can override per user; 0 = unlimited.
    storage_quota_mb: int = 500

    # Cleanup
    audio_retention_days: int = 14
    cleanup_interval_hours: int = 24

    model_config = SettingsConfigDict(env_file=str(STATE_DIR / ".env"), env_file_encoding="utf-8")


@lru_cache()
def get_settings() -> Settings:
    """The single shared ``Settings`` instance (cached for the process lifetime)."""
    return Settings()
