"""Per-user Google Drive: OAuth connection and "save this lecture to my Drive".

Each user can connect their own Google account from Settings. The app asks
only for the ``drive.file`` scope, so it can see and touch nothing in that
Drive except the files it creates itself: an "AI Lecture Notes" folder with
one subfolder per lecture holding ``notes.md``, ``transcript.txt`` and, when
the audio is still retained, ``recording.mp3``. Exporting the same lecture
again updates those files in place.

The Google refresh token is stored encrypted (Fernet, key derived from
SECRET_KEY). Exports run as background jobs — the MP3 alone can take a
minute for a long lecture — and the UI polls ``status()``.

Requires an OAuth client of type "Web application" (Settings → Google Drive)
whose authorised redirect URI is ``<PUBLIC_URL>/api/drive/callback``.
"""

import asyncio
import base64
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import mp3_export
from config import get_settings
from database import AsyncSessionLocal
from models import AudioChunk, DriveFile, DriveLink, NotesVersion, Session, TranscriptSegment

logger = logging.getLogger(__name__)
settings = get_settings()

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
DRIVE_API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
SCOPES = "https://www.googleapis.com/auth/drive.file openid email"
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_FOLDER_NAME = "AI Lecture Notes"
STATE_TTL = 600  # seconds a sign-in attempt stays valid


class DriveError(Exception):
    """Anything that stops an export or a connection, with a user-readable message."""


# ── Configuration ─────────────────────────────────────────────────────────────


def configured() -> bool:
    """Whether an admin has saved a Google OAuth client (Settings → Google Drive)."""
    return bool(settings.google_client_id and settings.google_client_secret)


def redirect_uri() -> str:
    """Where Google sends the user back; must match the OAuth client exactly."""
    base = settings.public_url.rstrip("/")
    return f"{base}/api/drive/callback"


# ── Token encryption ──────────────────────────────────────────────────────────


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
    return Fernet(key)


def encrypt(token: str) -> str:
    """Refresh token → ciphertext for the database."""
    return _fernet().encrypt(token.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Ciphertext → refresh token; raises DriveError if SECRET_KEY changed."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise DriveError("Stored Google credentials can't be read — reconnect Google Drive")


# ── OAuth ─────────────────────────────────────────────────────────────────────


def make_state(user_id: uuid.UUID) -> str:
    """Signed, expiring blob tying a sign-in attempt to the signed-in user."""
    payload = json.dumps({"u": str(user_id), "t": int(time.time())}).encode()
    return _fernet().encrypt(payload).decode()


def check_state(state: str, user_id: uuid.UUID) -> bool:
    """Whether ``state`` was issued for this user recently."""
    try:
        data = json.loads(_fernet().decrypt(state.encode(), ttl=STATE_TTL))
    except (InvalidToken, ValueError):
        return False
    return data.get("u") == str(user_id)


def auth_url(user_id: uuid.UUID) -> str:
    """The Google consent page URL for connecting a Drive."""
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",  # refresh token
        "prompt": "consent",  # Google only returns a refresh token on consent
        "include_granted_scopes": "true",
        "state": make_state(user_id),
    }
    return str(httpx.URL(AUTH_URL, params=params))


async def exchange_code(code: str) -> tuple[str, Optional[str]]:
    """Trade the callback code for a refresh token and the account's email."""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        if response.status_code != 200:
            raise DriveError(f"Google rejected the sign-in: {response.text[:200]}")
        tokens = response.json()
        refresh = tokens.get("refresh_token")
        if not refresh:
            raise DriveError("Google did not return a refresh token — try connecting again")
        email = None
        info = await client.get(
            USERINFO_URL, headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        if info.status_code == 200:
            email = info.json().get("email")
    return refresh, email


async def _access_token(refresh_token: str) -> str:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "grant_type": "refresh_token",
            },
        )
    if response.status_code != 200:
        raise DriveError("Google Drive access was revoked — reconnect it in Settings")
    return response.json()["access_token"]


async def revoke(refresh_token: str) -> None:
    """Tell Google the app no longer needs access (best effort)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(REVOKE_URL, params={"token": refresh_token})
    except httpx.HTTPError as e:
        logger.warning("Google token revoke failed: %s", e)


# ── Drive API ─────────────────────────────────────────────────────────────────


class Drive:
    """Minimal Drive v3 client bound to one access token."""

    def __init__(self, access_token: str):
        """Wrap an httpx client with the bearer header set."""
        self.client = httpx.AsyncClient(
            timeout=120, headers={"Authorization": f"Bearer {access_token}"}
        )

    async def close(self) -> None:
        """Release the connection pool."""
        await self.client.aclose()

    async def _check(self, response: httpx.Response) -> dict:
        if response.status_code >= 400:
            raise DriveError(f"Google Drive error {response.status_code}: {response.text[:200]}")
        return response.json() if response.content else {}

    async def exists(self, file_id: str) -> bool:
        """Whether a file/folder the app made still exists (not trashed)."""
        response = await self.client.get(
            f"{DRIVE_API}/files/{file_id}", params={"fields": "trashed"}
        )
        return response.status_code == 200 and not response.json().get("trashed")

    async def find_folder(self, name: str, parent: Optional[str]) -> Optional[str]:
        """Id of an untrashed folder with this name under ``parent`` (or root)."""
        safe = name.replace("\\", "\\\\").replace("'", "\\'")
        q = f"name = '{safe}' and mimeType = '{FOLDER_MIME}' and trashed = false"
        q += f" and '{parent}' in parents" if parent else " and 'root' in parents"
        data = await self._check(
            await self.client.get(f"{DRIVE_API}/files", params={"q": q, "fields": "files(id)"})
        )
        files = data.get("files", [])
        return files[0]["id"] if files else None

    async def create_folder(self, name: str, parent: Optional[str]) -> str:
        """Make a folder and return its id."""
        body = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            body["parents"] = [parent]
        data = await self._check(
            await self.client.post(f"{DRIVE_API}/files", json=body, params={"fields": "id"})
        )
        return data["id"]

    async def ensure_folder(self, name: str, parent: Optional[str]) -> str:
        """Find-or-create a folder."""
        return await self.find_folder(name, parent) or await self.create_folder(name, parent)

    async def upload(
        self, name: str, mime: str, content: bytes, parent: str, existing: Optional[str]
    ) -> str:
        """Create a file, or overwrite ``existing`` in place; returns the file id."""
        if existing and await self.exists(existing):
            data = await self._check(
                await self.client.patch(
                    f"{UPLOAD_API}/files/{existing}",
                    params={"uploadType": "media", "fields": "id"},
                    content=content,
                    headers={"Content-Type": mime},
                )
            )
            return data["id"]
        meta = json.dumps({"name": name, "parents": [parent]})
        files = {
            "metadata": ("metadata", meta, "application/json; charset=UTF-8"),
            "file": (name, content, mime),
        }
        data = await self._check(
            await self.client.post(
                f"{UPLOAD_API}/files",
                params={"uploadType": "multipart", "fields": "id"},
                files=files,
            )
        )
        return data["id"]


# ── Export jobs ───────────────────────────────────────────────────────────────


@dataclass
class Job:
    """One "save to Drive" run for a lecture."""

    session_id: str
    status: str = "running"  # running | done | error
    step: str = "Preparing"
    files: dict[str, str] = field(default_factory=dict)  # kind -> Drive file id
    folder_url: Optional[str] = None
    error: Optional[str] = None
    finished_at: Optional[float] = None

    def progress(self) -> dict:
        """The status payload the API returns."""
        return {
            "status": self.status,
            "step": self.step,
            "files": self.files,
            "folder_url": self.folder_url,
            "error": self.error,
        }


_jobs: dict[str, Job] = {}


def status(session_id: str) -> Optional[Job]:
    """The most recent export job for a lecture, if any."""
    return _jobs.get(session_id)


def start(session_id: str) -> Job:
    """Kick off an export unless one is already running."""
    job = _jobs.get(session_id)
    if job and job.status == "running":
        return job
    job = Job(session_id=session_id)
    _jobs[session_id] = job
    asyncio.create_task(_run(job))
    return job


async def auto_export(session_id: str) -> None:
    """Export after a recording stops, if the owner turned that on."""
    async with AsyncSessionLocal() as db:
        session = await db.get(Session, session_id)
        if session is None or session.user_id is None:
            return
        link = await db.get(DriveLink, session.user_id)
    if link and link.auto_export:
        logger.info("Auto-saving session %s to Google Drive", session_id)
        start(session_id)


def _slug(title: Optional[str], created_at: datetime) -> str:
    base = (title or "Untitled lecture").strip() or "Untitled lecture"
    base = "".join(ch for ch in base if ch not in '\\/:*?"<>|').strip()[:80]
    return f"{created_at:%Y-%m-%d} {base}"


async def _run(job: Job) -> None:
    drive: Optional[Drive] = None
    try:
        async with AsyncSessionLocal() as db:
            session = await db.get(Session, job.session_id)
            if session is None or session.user_id is None:
                raise DriveError("Lecture not found")
            link = await db.get(DriveLink, session.user_id)
            if link is None:
                raise DriveError("Google Drive is not connected")
            existing = {
                f.kind: f
                for f in (
                    await db.execute(select(DriveFile).where(DriveFile.session_id == session.id))
                )
                .scalars()
                .all()
            }
            notes, transcript, keys = await _contents(db, session)
            drive = Drive(await _access_token(decrypt(link.refresh_token)))

            job.step = "Creating folder"
            root = link.folder_id
            if not root or not await drive.exists(root):
                root = await drive.ensure_folder(ROOT_FOLDER_NAME, None)
                link.folder_id = root
                await db.commit()
            folder_name = _slug(session.title, session.created_at)
            prior = next((f.folder_id for f in existing.values() if f.folder_id), None)
            folder = prior if prior and await drive.exists(prior) else None
            folder = folder or await drive.ensure_folder(folder_name, root)
            job.folder_url = f"https://drive.google.com/drive/folders/{folder}"

            async def put(kind: str, name: str, mime: str, content: bytes) -> None:
                job.step = f"Uploading {name}"
                file_id = await drive.upload(
                    name,
                    mime,
                    content,
                    folder,
                    existing[kind].file_id if kind in existing else None,
                )
                if kind in existing:
                    existing[kind].file_id = file_id
                    existing[kind].folder_id = folder
                    existing[kind].updated_at = datetime.utcnow()
                else:
                    db.add(
                        DriveFile(
                            session_id=session.id, kind=kind, file_id=file_id, folder_id=folder
                        )
                    )
                await db.commit()
                job.files[kind] = file_id

            await put("transcript", "transcript.txt", "text/plain", transcript.encode())
            if notes:
                await put("notes", "notes.md", "text/markdown", notes.encode())
            if keys:
                job.step = "Converting audio to MP3"
                mp3 = await mp3_export.wait(mp3_export.start(session.id, keys, "recording.mp3"))
                if mp3.status != "ready" or not mp3.path:
                    raise DriveError(f"Audio conversion failed: {mp3.error}")
                with open(mp3.path, "rb") as f:
                    await put("audio", "recording.mp3", "audio/mpeg", f.read())
        job.status = "done"
        job.step = "Saved"
        logger.info("Session %s saved to Google Drive (%s)", job.session_id, list(job.files))
    except DriveError as e:
        job.status, job.error = "error", str(e)
        logger.warning("Drive export failed for %s: %s", job.session_id, e)
    except Exception as e:  # noqa: BLE001 — any failure is reported to the UI
        job.status, job.error = "error", f"{type(e).__name__}: {e}"[:300]
        logger.exception("Drive export crashed for %s", job.session_id)
    finally:
        job.finished_at = time.time()
        if drive:
            await drive.close()


async def _contents(db: AsyncSession, session: Session) -> tuple[Optional[str], str, list[str]]:
    """Latest notes (Markdown), the transcript text, and retained chunk keys."""
    notes_row = (
        await db.execute(
            select(NotesVersion)
            .where(NotesVersion.session_id == session.id)
            .order_by(NotesVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    title = session.title or f"Lecture - {session.id[:8]}"
    notes = f"# {title}\n\n{notes_row.notes_md}" if notes_row else None

    segments = (
        (
            await db.execute(
                select(TranscriptSegment)
                .where(TranscriptSegment.session_id == session.id)
                .order_by(TranscriptSegment.chunk_index, TranscriptSegment.ts_start)
            )
        )
        .scalars()
        .all()
    )
    lines = [title, "=" * len(title), ""]
    for seg in segments:
        lines.append(f"[{int(seg.ts_start // 60):02d}:{seg.ts_start % 60:05.2f}] {seg.text}")
    transcript = "\n".join(lines)

    chunks = (
        (
            await db.execute(
                select(AudioChunk)
                .where(AudioChunk.session_id == session.id, AudioChunk.deleted_from_s3.is_(False))
                .order_by(AudioChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    keys = [c.s3_key for c in chunks if c.s3_key]
    return notes, transcript, keys
