"""Pydantic models for the HTTP API and the WebSocket message payloads.

Response models with ``from_attributes = True`` are built straight from
SQLAlchemy rows; the rest describe request bodies or hand-assembled replies.
Field comments explain anything that isn't obvious from the name.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# ── Lecture sessions ──────────────────────────────────────────────────────────


class SessionResponse(BaseModel):
    """A lecture session row (``GET /api/session/{id}``)."""

    id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_notes_version: int
    vocabulary: Optional[str] = None  # key terms for the transcriber
    notes_focus: Optional[str] = None  # what the notes should emphasise

    model_config = ConfigDict(from_attributes=True)


class SessionDetails(BaseModel):
    """Editable per-lecture settings (``PATCH /api/session/{id}``)."""

    title: Optional[str] = None
    vocabulary: Optional[str] = None
    notes_focus: Optional[str] = None


class NotesEdit(BaseModel):
    """A user's own version of the notes (``PUT /api/session/{id}/notes``)."""

    notes_md: str


class TranscriptResponse(BaseModel):
    """The whole transcript of a session joined into one string."""

    session_id: str
    text: str
    segment_count: int


class NotesResponse(BaseModel):
    """The latest generated notes for a session, as Markdown."""

    session_id: str
    version: int
    notes_md: str
    created_at: datetime


class AudioChunkResponse(BaseModel):
    """One uploaded 5-second audio chunk and what happened to it."""

    id: UUID
    chunk_index: int
    s3_key: Optional[str]
    size_bytes: int
    received_at: datetime
    decode_ok: bool
    transcribed_ok: bool
    error: Optional[str]
    deleted_from_s3: bool
    deleted_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class AudioChunksListResponse(BaseModel):
    """All chunks of a session, in upload order."""

    session_id: str
    chunks: list[AudioChunkResponse]


class CleanupResponse(BaseModel):
    """Result of a retention-cleanup pass (``POST /api/admin/cleanup_audio``)."""

    sessions_scanned: int
    chunks_deleted: int
    errors: list[str]


class DocumentUploadResponse(BaseModel):
    """A slide deck, document or image attached to a session."""

    id: UUID
    filename: str
    file_type: str  # pdf | pptx | docx | image
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Chat ──────────────────────────────────────────────────────────────────────


class ChatTurn(BaseModel):
    """One earlier message in the chat, so follow-ups like "when is that due?" resolve."""

    role: str  # "user" | "assistant"
    text: str


class ChatRequest(BaseModel):
    """A question about the lecture, optionally with a pasted image."""

    message: str
    image_base64: Optional[str] = None  # base64-encoded image, data-URL prefix stripped
    image_media_type: Optional[str] = None  # e.g. "image/png"
    history: list[ChatTurn] = []  # the most recent exchanges, oldest first


class ChatMessageOut(BaseModel):
    """A stored chat turn (``GET /api/session/{id}/chat``)."""

    role: str
    text: str
    provider: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class ChatResponse(BaseModel):
    """The assistant's answer and which provider produced it."""

    answer: str
    session_id: str
    provider: Optional[str] = None  # e.g. gemini/gemini-3.6-flash, ollama/llama3, llava, blip
    fallback: Optional[str] = None  # e.g. "Gemini unavailable: quota or rate limit exceeded"


# ── WebSocket messages (server → browser) ─────────────────────────────────────


class TranscriptDelta(BaseModel):
    """A newly transcribed segment, sent as soon as a chunk is processed."""

    type: str = "transcript_delta"
    text: str
    chunk: int
    segment_id: str
    ts_start: float
    ts_end: float


class NotesUpdate(BaseModel):
    """A new version of the notes (every ``notes_interval_seconds`` and on stop)."""

    type: str = "notes_update"
    notes_md: str
    version: int


class StatusMessage(BaseModel):
    """A human-readable status line shown in the toolbar."""

    type: str = "status"
    message: str


# ── Settings (admin) ──────────────────────────────────────────────────────────


class AuthStatus(BaseModel):
    """Which Anthropic credential the SDK would use, and any misconfiguration."""

    source: str  # api_key | auth_token | profile | misconfigured | none
    detail: str
    key_masked: Optional[str] = None  # last four characters only
    profile_on_disk: bool
    sdk_version: str
    sdk_supports_profiles: bool
    warnings: list[str] = []


class SettingsResponse(BaseModel):
    """Everything the Settings panel shows.

    ``text_provider`` / ``vision_provider`` are what the admin chose;
    ``active_*`` are what will actually run, which differs when the chosen
    provider has no API key saved.
    """

    auth: AuthStatus
    vision_model: str
    ollama_model: str
    whisper_model: str
    notes_interval_seconds: int
    storage_quota_mb: int
    audio_retention_days: int
    whisper_language: str = "en"
    whisper_vocabulary: str = ""
    registration_open: bool
    registration_approval: bool = False
    mail_configured: bool
    max_locked_lectures: int
    text_provider: str
    active_text_provider: str
    vision_provider: str
    active_vision_provider: str
    claude_text_model: str
    gemini_model: str
    gemini_key_masked: Optional[str] = None
    openai_model: str
    openai_key_masked: Optional[str] = None
    google_client_id: str = ""
    google_client_secret_masked: Optional[str] = None
    google_redirect_uri: str = ""
    ollama_base_url: str
    ollama_reachable: bool
    restart_required: list[str] = []  # saved fields that only apply after a restart


class SettingsUpdate(BaseModel):
    """A partial update from the Settings panel.

    Every field is optional: the panel PUTs only what changed. Unknown fields
    are rejected rather than ignored — silently accepting
    ``{"database_url": ...}`` would look like it had been applied.
    API-key fields: ``""`` clears the key; keys are never echoed back.
    """

    model_config = ConfigDict(extra="forbid")

    anthropic_api_key: Optional[str] = None
    vision_model: Optional[str] = None
    ollama_model: Optional[str] = None
    whisper_model: Optional[str] = None
    notes_interval_seconds: Optional[int] = None
    storage_quota_mb: Optional[int] = None
    audio_retention_days: Optional[int] = None
    whisper_language: Optional[str] = None
    whisper_vocabulary: Optional[str] = None
    registration_open: Optional[bool] = None
    registration_approval: Optional[bool] = None
    max_locked_lectures: Optional[int] = None
    text_provider: Optional[str] = None
    vision_provider: Optional[str] = None
    claude_text_model: Optional[str] = None
    gemini_model: Optional[str] = None
    gemini_api_key: Optional[str] = None
    openai_model: Optional[str] = None
    openai_api_key: Optional[str] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None


class ProviderTest(BaseModel):
    """Result of a connectivity check against one AI provider."""

    provider: str
    ok: bool
    detail: str


class ModelOption(BaseModel):
    """One entry in a provider's model dropdown."""

    id: str  # the model name sent to the API
    label: str  # human-readable display name


# ── Accounts ──────────────────────────────────────────────────────────────────


class LoginRequest(BaseModel):
    """Sign-in form; ``username`` also accepts an email address."""

    username: str
    password: str


class UserResponse(BaseModel):
    """A user as returned to the client — never includes the password hash."""

    id: UUID
    username: str
    email: Optional[str] = None
    is_admin: bool
    disabled: bool
    quota_mb: Optional[int] = None  # None = global default applies
    email_verified: bool = True
    approved: bool = True  # False = waiting for an admin (Settings → Users → Approve)
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class AccountDelete(BaseModel):
    """Password confirmation for deleting one's own account."""

    password: str


class RegistrationPending(BaseModel):
    """Reply to a registration that needs the emailed link first (HTTP 202)."""

    pending_verification: bool = True
    email: str
    message: str


class UserCreate(BaseModel):
    """Admin-created account (``POST /api/auth/users``)."""

    username: str
    password: str
    email: Optional[str] = None
    is_admin: bool = False


class RegisterRequest(BaseModel):
    """Self-registration from the sign-in page; email is required here."""

    username: str
    email: str
    password: str


class ProfileUpdate(BaseModel):
    """Fields a user may change on their own account."""

    email: Optional[str] = None


class RegistrationStatus(BaseModel):
    """What the sign-in page may offer (read without a login)."""

    registration_open: bool
    registration_approval: bool = False  # new accounts wait for an admin
    password_reset_available: bool  # True when outgoing mail is configured


class ForgotPasswordRequest(BaseModel):
    """Request a reset link; the identifier is a username or an email."""

    identifier: str


class ResetPasswordRequest(BaseModel):
    """Complete a reset with the token from the emailed link."""

    token: str
    new_password: str


class PasswordChange(BaseModel):
    """A signed-in user changing their own password."""

    current_password: str
    new_password: str


class PasswordReset(BaseModel):
    """An admin setting a new password for another user."""

    new_password: str


class UserUpdate(BaseModel):
    """Admin edits to a user; ``clear_quota`` restores the global default."""

    quota_mb: Optional[int] = None  # 0 = unlimited
    clear_quota: bool = False


class StorageUsage(BaseModel):
    """The signed-in user's retained-audio usage and lock allowance."""

    used_bytes: int
    quota_bytes: int  # 0 = unlimited
    locked_count: int = 0
    lock_limit: int = 0  # 0 = unlimited (admins)
    retention_days: int = 14  # audio is deleted after this many days unless kept


# ── History ───────────────────────────────────────────────────────────────────


class SessionSummary(BaseModel):
    """One row of the History drawer."""

    id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    segment_count: int
    notes_version: int
    duration_seconds: int  # approximate: chunk count × 5 s
    has_audio: bool  # any chunk still in object storage
    locked: bool = False  # "kept": exempt from cleanup and deletion
    owner: Optional[str] = None  # username; only filled in for admins
    drive_saved_at: Optional[datetime] = None  # last "save to Google Drive"


class SessionRename(BaseModel):
    """New title for a lecture."""

    title: str


class SessionLock(BaseModel):
    """Keep (``true``) or release (``false``) a lecture."""

    locked: bool


class DriveStatus(BaseModel):
    """The signed-in user's Google Drive connection (``GET /api/drive``)."""

    available: bool  # an admin has configured a Google OAuth client
    connected: bool
    email: Optional[str] = None
    auto_export: bool = False
    folder_name: str = "AI Lecture Notes"
    folder_url: Optional[str] = None


class DriveUpdate(BaseModel):
    """Change automatic saving and/or the folder path in Drive."""

    auto_export: Optional[bool] = None
    folder_name: Optional[str] = None
