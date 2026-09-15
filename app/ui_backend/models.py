"""SQLAlchemy ORM models — the database schema.

One ``Session`` is one lecture recording. Everything else hangs off it:
audio chunks (5-second uploads), transcript segments (Whisper output), notes
versions (one per generation pass) and uploaded documents. ``User`` owns
sessions; ``PasswordReset`` holds hashed reset tokens; ``DriveLink`` is a
user's connected Google Drive and ``DriveFile`` what has been saved there.

Schema changes go through Alembic (``alembic/versions``); the app applies
pending migrations on startup.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    """An account. Passwords are bcrypt hashes; ``email`` is stored lowercase
    and doubles as a sign-in identifier. ``disabled`` blocks sign-in without
    deleting the row (and the lectures it owns)."""

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(64), unique=True, nullable=False)
    email = Column(String(254), unique=True, nullable=True)  # stored lowercase
    password_hash = Column(Text, nullable=False)
    is_admin = Column(Boolean, default=False, nullable=False)
    disabled = Column(Boolean, default=False, nullable=False)
    quota_mb = Column(Integer, nullable=True)  # per-user audio quota; null = global default
    # False only for self-registered accounts that haven't clicked the emailed link yet.
    email_verified = Column(Boolean, default=True, nullable=False, server_default="true")
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("Session", back_populates="user")


class PasswordReset(Base):
    """A single-use password-reset token.

    Only the SHA-256 of the emailed token is stored, so a database read cannot
    reproduce a valid link. ``used_at`` is set on completion (and on every
    other outstanding token for that user).
    """

    __tablename__ = "password_resets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash = Column(String(64), unique=True, nullable=False)  # sha256 of the emailed token
    purpose = Column(String(16), nullable=False, default="reset")  # "reset" | "verify"
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Session(Base):
    """A lecture recording: the unit users see in History.

    Created on the first WebSocket connection for a browser-generated UUID, so
    empty rows exist for page loads that never recorded; History hides those.
    ``last_summarized_segment_id`` marks how far the incremental notes
    generator has read.
    """

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True)
    # Null only for sessions recorded before accounts existed; those are admin-only.
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    title = Column(Text, nullable=True)
    # Kept: exempt from the audio retention cleanup and from deletion until unlocked.
    locked = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_notes_version = Column(Integer, default=0)
    last_summarized_segment_id = Column(UUID(as_uuid=True), nullable=True)

    audio_chunks = relationship(
        "AudioChunk", back_populates="session", cascade="all, delete-orphan"
    )
    transcript_segments = relationship(
        "TranscriptSegment", back_populates="session", cascade="all, delete-orphan"
    )
    notes_versions = relationship(
        "NotesVersion", back_populates="session", cascade="all, delete-orphan"
    )
    documents = relationship(
        "DocumentUpload", back_populates="session", cascade="all, delete-orphan"
    )
    user = relationship("User", back_populates="sessions")


class AudioChunk(Base):
    """One 5-second WebM/Opus upload from the browser.

    The bytes live in object storage (``s3_key``); the row records whether it
    decoded and transcribed, and ``deleted_from_s3`` once retention, the user,
    or "Don't keep audio" removed it. Chunk 0 also carries the WebM header the
    later chunks need to decode (see ``websocket_handler``).
    """

    __tablename__ = "audio_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    received_at = Column(DateTime, default=datetime.utcnow)
    s3_bucket = Column(Text, nullable=True)
    s3_key = Column(Text, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    decode_ok = Column(Boolean, default=False)
    transcribed_ok = Column(Boolean, default=False)
    error = Column(Text, nullable=True)
    deleted_from_s3 = Column(Boolean, default=False)
    deleted_at = Column(DateTime, nullable=True)

    session = relationship("Session", back_populates="audio_chunks")

    __table_args__ = (Index("ix_audio_chunks_session_chunk", "session_id", "chunk_index"),)


class TranscriptSegment(Base):
    """A piece of transcribed speech with timestamps relative to its chunk."""

    __tablename__ = "transcript_segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    ts_start = Column(Float, nullable=False)
    ts_end = Column(Float, nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="transcript_segments")

    __table_args__ = (Index("ix_transcript_segments_session_created", "session_id", "created_at"),)


class NotesVersion(Base):
    """A snapshot of the notes; a new version is written on every pass."""

    __tablename__ = "notes_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    version = Column(Integer, nullable=False)
    notes_md = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="notes_versions")

    __table_args__ = (Index("ix_notes_versions_session_version", "session_id", "version"),)


class DocumentUpload(Base):
    """A slide deck, document or image attached to a lecture.

    Only the extracted text is kept (images are transcribed by a vision
    model on upload); it is fed to the chat as context.
    """

    __tablename__ = "document_uploads"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(36), ForeignKey("sessions.id"), nullable=False)
    filename = Column(Text, nullable=False)
    file_type = Column(Text, nullable=False)  # "pdf", "pptx", "docx" or "image"
    extracted_text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship("Session", back_populates="documents")


class DriveLink(Base):
    """A user's connected Google Drive (one per user).

    ``refresh_token`` is encrypted with the app's SECRET_KEY (see
    ``google_drive``). ``folder_id`` is the "AI Lecture Notes" folder the app
    created in that Drive; the ``drive.file`` scope means the app can see
    nothing else there.
    """

    __tablename__ = "drive_links"

    user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    google_email = Column(String(254), nullable=True)
    refresh_token = Column(Text, nullable=False)
    # Path the user wants, e.g. "School/Fall 2026"; created on first export.
    folder_name = Column(String(255), nullable=False, default="AI Lecture Notes")
    folder_id = Column(String(128), nullable=True)
    auto_export = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class DriveFile(Base):
    """One file the app put in a user's Drive for a lecture — remembered so a
    later export updates it in place instead of creating a duplicate."""

    __tablename__ = "drive_files"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = Column(String(16), nullable=False)  # "notes" | "transcript" | "audio"
    file_id = Column(String(128), nullable=False)
    folder_id = Column(String(128), nullable=True)  # the lecture's own subfolder
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_drive_files_session_kind", "session_id", "kind", unique=True),)
