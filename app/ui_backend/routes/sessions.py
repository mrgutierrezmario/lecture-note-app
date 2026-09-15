"""Per-lecture API: transcript, notes, exports, uploads, audio and chat.

Every route lives under ``/api/session/{session_id}`` and passes through
``session_access`` first, so a user can only touch their own lectures (admins
can touch any). Images are read by the configured cloud vision provider with
local llava and BLIP as fallbacks.
"""

import base64
import logging

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import google_drive
import mp3_export
from auth import CurrentUser, current_user
from config import get_settings
from database import get_db
from document_processor import extract_text, image_media_type
from image_analyzer import caption_image as blip_caption
from models import AudioChunk, DocumentUpload, DriveLink, NotesVersion, Session, TranscriptSegment
from s3_client import s3_client
from schemas import (
    AudioChunkResponse,
    AudioChunksListResponse,
    ChatRequest,
    ChatResponse,
    DocumentUploadResponse,
    NotesResponse,
    SessionResponse,
    TranscriptResponse,
)

logger = logging.getLogger(__name__)


async def session_access(
    session_id: str, user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Every route here is scoped to one session: the owner or an admin may use
    it. Sessions recorded before accounts existed have no owner and are
    admin-only. A session that does not exist yet (the first websocket 'start'
    creates it) is fine — the caller will get a 404 from its own lookup."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if session is not None and not user.is_admin and session.user_id != user.id:
        raise HTTPException(status_code=403, detail="This lecture belongs to another user")


router = APIRouter(prefix="/api/session", tags=["sessions"], dependencies=[Depends(session_access)])


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Basic details of one lecture."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return session


@router.get("/{session_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(session_id: str, db: AsyncSession = Depends(get_db)):
    """The full transcript as one string, in spoken order."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    segments_result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.chunk_index, TranscriptSegment.ts_start)
    )
    segments = segments_result.scalars().all()

    full_text = " ".join([seg.text for seg in segments])

    return TranscriptResponse(
        session_id=session_id,
        text=full_text,
        segment_count=len(segments),
    )


@router.get("/{session_id}/notes", response_model=NotesResponse)
async def get_notes(session_id: str, db: AsyncSession = Depends(get_db)):
    """The newest notes version; 404 until the first pass has run."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    notes_result = await db.execute(
        select(NotesVersion)
        .where(NotesVersion.session_id == session_id)
        .order_by(NotesVersion.version.desc())
        .limit(1)
    )
    notes = notes_result.scalar_one_or_none()

    if not notes:
        return NotesResponse(
            session_id=session_id,
            version=0,
            notes_md="*No notes generated yet.*",
            created_at=session.created_at,
        )

    return NotesResponse(
        session_id=session_id,
        version=notes.version,
        notes_md=notes.notes_md,
        created_at=notes.created_at,
    )


@router.get("/{session_id}/export/notes.md")
async def export_notes(session_id: str, db: AsyncSession = Depends(get_db)):
    """Download the newest notes as a Markdown file."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    notes_result = await db.execute(
        select(NotesVersion)
        .where(NotesVersion.session_id == session_id)
        .order_by(NotesVersion.version.desc())
        .limit(1)
    )
    notes = notes_result.scalar_one_or_none()

    title = session.title or f"Lecture Notes - {session_id}"

    if notes:
        content = f"# {title}\n\n{notes.notes_md}"
    else:
        content = f"# {title}\n\n*No notes generated yet.*"

    filename = f"notes-{session_id[:8]}.md"

    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/export/transcript.txt")
async def export_transcript(session_id: str, db: AsyncSession = Depends(get_db)):
    """Download the full transcript as a text file."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    segments_result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.chunk_index, TranscriptSegment.ts_start)
    )
    segments = segments_result.scalars().all()

    title = session.title or f"Lecture - {session_id[:8]}"
    lines = [title, "=" * len(title), ""]
    for seg in segments:
        minutes = int(seg.ts_start // 60)
        seconds = seg.ts_start % 60
        lines.append(f"[{minutes:02d}:{seconds:05.2f}] {seg.text}")

    content = "\n".join(lines)
    filename = f"transcript-{session_id[:8]}.txt"
    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _mp3_inputs(session_id: str, db: AsyncSession) -> tuple[list[str], str]:
    """Object keys of the retained chunks (in order) and the download filename."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    chunks_result = await db.execute(
        select(AudioChunk)
        .where(AudioChunk.session_id == session_id, AudioChunk.deleted_from_s3.is_(False))
        .order_by(AudioChunk.chunk_index)
    )
    keys = [c.s3_key for c in chunks_result.scalars().all() if c.s3_key]
    if not keys:
        raise HTTPException(status_code=404, detail="No audio chunks found for this session")
    title_slug = (session.title or session_id[:8]).replace(" ", "-")
    return keys, f"recording-{title_slug[:30]}.mp3"


@router.post("/{session_id}/export/audio.mp3/prepare")
async def prepare_audio(session_id: str, db: AsyncSession = Depends(get_db)):
    """Start building the MP3 in the background and return its progress.

    The UI polls ``…/status`` and shows a spinner until ``status`` is
    ``ready``, then fetches ``…/export/audio.mp3`` which serves instantly.
    """
    keys, filename = await _mp3_inputs(session_id, db)
    return mp3_export.start(session_id, keys, filename).progress()


@router.get("/{session_id}/export/audio.mp3/status")
async def audio_status(session_id: str):
    """Progress of the MP3 build for a session (``status: none`` if not started)."""
    job = mp3_export.status(session_id)
    return job.progress() if job else {"status": "none"}


@router.post("/{session_id}/drive")
async def save_to_drive(
    session_id: str, user: CurrentUser = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Save notes, transcript and MP3 to the *owner's* Google Drive (background).

    Poll ``…/drive/status``. Admins may trigger it for another user's lecture;
    the files still land in that user's Drive, never the admin's.
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.user_id is None:
        raise HTTPException(status_code=400, detail="This lecture has no owner")
    link = await db.get(DriveLink, session.user_id)
    if link is None:
        raise HTTPException(status_code=400, detail="Google Drive is not connected (Settings)")
    return google_drive.start(session_id).progress()


@router.get("/{session_id}/drive/status")
async def drive_status(session_id: str):
    """Progress of the last "save to Drive" for this lecture (``status: none`` if never)."""
    job = google_drive.status(session_id)
    return job.progress() if job else {"status": "none"}


@router.get("/{session_id}/export/audio.mp3")
async def export_audio(session_id: str, db: AsyncSession = Depends(get_db)):
    """Download the whole recording as one MP3.

    Serves the prepared file when one exists; otherwise builds it first (so a
    plain link still works, it just waits).
    """
    keys, filename = await _mp3_inputs(session_id, db)
    job = await mp3_export.wait(mp3_export.start(session_id, keys, filename))
    if job.status != "ready" or not job.path:
        raise HTTPException(status_code=500, detail=f"Audio conversion failed: {job.error}")
    return FileResponse(
        job.path,
        media_type="audio/mpeg",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/audio/chunks", response_model=AudioChunksListResponse)
async def list_audio_chunks(session_id: str, db: AsyncSession = Depends(get_db)):
    """Metadata for every chunk of a lecture (debugging aid)."""
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    chunks_result = await db.execute(
        select(AudioChunk)
        .where(AudioChunk.session_id == session_id)
        .order_by(AudioChunk.chunk_index)
    )
    chunks = chunks_result.scalars().all()

    return AudioChunksListResponse(
        session_id=session_id,
        chunks=[AudioChunkResponse.model_validate(c) for c in chunks],
    )


@router.get("/{session_id}/audio/chunks/{chunk_index}")
async def stream_audio_chunk(
    session_id: str,
    chunk_index: int,
    db: AsyncSession = Depends(get_db),
):
    """Stream one raw WebM chunk from object storage."""
    result = await db.execute(
        select(AudioChunk).where(
            AudioChunk.session_id == session_id,
            AudioChunk.chunk_index == chunk_index,
        )
    )
    chunk = result.scalar_one_or_none()

    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")

    if chunk.deleted_from_s3 or not chunk.s3_key:
        raise HTTPException(status_code=410, detail="Chunk has been deleted from storage")

    try:
        stream = s3_client.stream_chunk(chunk.s3_key)
        return StreamingResponse(
            stream,
            media_type="audio/webm",
            headers={"Content-Disposition": f'inline; filename="chunk-{chunk_index}.webm"'},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/documents", response_model=DocumentUploadResponse)
async def upload_document(
    session_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Attach a PDF, PowerPoint, Word file or image to the lecture.

    Text is extracted (or, for images, transcribed by a vision model) and
    stored; the chat uses it as context. Bounded by ``max_upload_mb``.
    """
    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Bounded read: never let one upload grow the process by more than the cap.
    limit = get_settings().max_upload_mb * 1024 * 1024
    if file.size is not None and file.size > limit:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than the {get_settings().max_upload_mb} MB limit",
        )
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"File is larger than the {get_settings().max_upload_mb} MB limit",
        )
    media_type = image_media_type(file.filename)
    if media_type:
        # Images have no text layer: run them through the vision chain once and
        # store the transcription, so chat and notes treat them like any document.
        try:
            extracted_text, provider = await _transcribe_image(
                base64.b64encode(content).decode(), media_type
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read image: {e}")
        file_type = "image"
        logger.info("Image %s transcribed by %s", file.filename, provider)
    else:
        try:
            file_type, extracted_text = extract_text(file.filename, content)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to extract text: {e}")

    doc = DocumentUpload(
        session_id=session_id,
        filename=file.filename,
        file_type=file_type,
        extracted_text=extracted_text,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


def _image_question_prompt(question: str, context: str) -> str:
    return (
        "You are a helpful teaching assistant. "
        "The student has shared an image and asked a question.\n\n"
        f"Lecture context:\n{context}\n\n"
        f"Question about the image: {question}\n\n"
        f"Describe what you see in the image and answer the question."
    )


IMAGE_TRANSCRIBE_PROMPT = (
    "This image is a slide, whiteboard photo, or page from a lecture. "
    "Transcribe every piece of text in it exactly, preserving headings, bullets and order. "
    "Then, under a 'Figures:' heading, briefly describe any diagrams, charts, equations or "
    "pictures and what they show. Output plain text only, no commentary."
)


async def _describe_image_llava(
    image_base64: str, prompt: str, ollama_base_url: str, num_predict: int = 600
) -> str:
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{ollama_base_url}/api/generate",
            json={
                "model": "llava",
                "prompt": prompt,
                "images": [image_base64],
                "stream": False,
                "options": {"temperature": 0.1, "num_predict": num_predict},
            },
        )
        if response.status_code == 200:
            return response.json().get("response", "").strip()
        return "Sorry, I could not analyze the image at this time."


async def _transcribe_image(image_base64: str, media_type: str) -> tuple[str, str]:
    """Turn an uploaded image into document text. Returns (text, provider).

    Same tiers as chat: Claude reads slide text faithfully, llava roughly, and
    BLIP only produces a one-line caption — so the result is labelled with the
    provider so a weak transcription is visible in the stored text.
    """
    settings = get_settings()
    from providers import active_vision_provider, describe_image_cloud

    if active_vision_provider() != "llava":
        try:
            return await describe_image_cloud(
                image_base64, media_type, IMAGE_TRANSCRIBE_PROMPT, max_tokens=2048
            )
        except Exception as e:
            logger.warning(
                "Cloud image transcription failed (%s: %s) — falling back to llava",
                type(e).__name__,
                e,
            )
    try:
        text = await _describe_image_llava(
            image_base64, IMAGE_TRANSCRIBE_PROMPT, settings.ollama_base_url, num_predict=1200
        )
        if text and not text.startswith("Sorry, I could not"):
            return text, "llava"
    except Exception as e:
        logger.warning(
            "llava image transcription failed (%s: %s) — falling back to BLIP", type(e).__name__, e
        )
    caption = await blip_caption(image_base64)
    return f"[Image caption only — no vision model available to read text]\n{caption}", "blip"


@router.post("/{session_id}/chat", response_model=ChatResponse)
async def chat(
    session_id: str,
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
):
    """Answer a question about the lecture.

    With an image attached the configured vision provider answers (falling
    back to llava, then a BLIP caption + text model). Otherwise the text
    provider answers from the transcript and uploaded documents only.
    """
    settings = get_settings()

    result = await db.execute(select(Session).where(Session.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Fetch transcript
    segments_result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.session_id == session_id)
        .order_by(TranscriptSegment.chunk_index, TranscriptSegment.ts_start)
    )
    segments = segments_result.scalars().all()
    transcript_text = " ".join([s.text for s in segments]) if segments else ""

    # Fetch uploaded documents
    docs_result = await db.execute(
        select(DocumentUpload).where(DocumentUpload.session_id == session_id)
    )
    docs = docs_result.scalars().all()

    # Latest notes: a compact summary of the whole lecture so far, so questions
    # about earlier material can be answered even when the transcript is trimmed.
    notes_result = await db.execute(
        select(NotesVersion)
        .where(NotesVersion.session_id == session_id)
        .order_by(NotesVersion.version.desc())
        .limit(1)
    )
    latest_notes = notes_result.scalar_one_or_none()

    # How much transcript the active text provider can take. Cloud models have
    # very large context windows; local Ollama is bounded by num_ctx (set in
    # providers.py), so keep its share modest.
    from providers import active_provider

    transcript_budget = 16_000 if active_provider() == "ollama" else 300_000

    context_parts = []
    if latest_notes and latest_notes.notes_md.strip():
        context_parts.append(f"## Lecture Notes (so far)\n{latest_notes.notes_md[:20_000]}")
    if transcript_text:
        window = transcript_text[-transcript_budget:]
        label = (
            "Lecture Transcript"
            if len(window) == len(transcript_text)
            else "Lecture Transcript (most recent part)"
        )
        context_parts.append(f"## {label}\n{window}")
    for doc in docs:
        context_parts.append(f"## Document: {doc.filename}\n{doc.extracted_text[:20_000]}")

    context = "\n\n".join(context_parts) if context_parts else "No lecture content available yet."
    # Recent exchanges, so a follow-up ("when is that due?") has its referent.
    # Bounded so a long chat can't crowd out the lecture itself.
    turns = [t for t in request.history[-8:] if t.text.strip() and t.text != "(image)"]
    if turns:
        lines = [
            f"{'Student' if t.role == 'user' else 'Assistant'}: {t.text.strip()[:1500]}"
            for t in turns
        ]
        context += "\n\n## Conversation so far\n" + "\n\n".join(lines)

    # Image path: Claude API → llava fallback → error
    if request.image_base64:
        if len(request.image_base64) > get_settings().max_upload_mb * 1024 * 1024:
            raise HTTPException(
                status_code=413,
                detail=f"Image is larger than the {get_settings().max_upload_mb} MB limit",
            )
        media_type = request.image_media_type or "image/png"
        answer = None
        provider = None
        # Three tiers, best first. Each failure is logged: a swallowed error here
        # is indistinguishable to the student from a bad answer, because the chain
        # silently degrades to a generic BLIP caption.
        from providers import active_vision_provider, describe_image_cloud

        if active_vision_provider() != "llava":
            try:
                answer, provider = await describe_image_cloud(
                    request.image_base64,
                    media_type,
                    _image_question_prompt(request.message, context),
                )
            except Exception as e:
                if "credit balance" in str(e).lower():
                    answer = (
                        "Image analysis requires API credits for the selected provider — "
                        "add credits or pick another provider in Settings."
                    )
                    provider = "no-credits"
                    logger.warning("Cloud vision unavailable: no API credits")
                else:
                    logger.warning(
                        "Cloud vision failed (%s: %s) — falling back to llava", type(e).__name__, e
                    )
        else:
            logger.info("No cloud vision provider configured — using llava")
        if answer is None:
            try:
                answer = await _describe_image_llava(
                    request.image_base64,
                    _image_question_prompt(request.message, context),
                    settings.ollama_base_url,
                )
                provider = "llava"
            except Exception as e:
                logger.warning(
                    "llava vision failed (%s: %s) — falling back to local BLIP", type(e).__name__, e
                )

        if answer is None:
            try:
                logger.info("Using local BLIP model for image analysis")
                caption = await blip_caption(request.image_base64)
                prompt = (
                    f"You are a helpful teaching assistant. A student shared an image.\n\n"
                    f"Image description: {caption}\n\n"
                    f"Lecture context:\n{context}\n\n"
                    f"Student question: {request.message}\n\n"
                    "Answer the student's question using the image description "
                    "and lecture context."
                )
                async with httpx.AsyncClient(timeout=60.0) as client:
                    r = await client.post(
                        f"{settings.ollama_base_url}/api/generate",
                        json={
                            "model": settings.ollama_model,
                            "prompt": prompt,
                            "stream": False,
                            "options": {"temperature": 0.1, "num_predict": 400},
                        },
                    )
                    answer = (
                        r.json().get("response", "").strip()
                        if r.status_code == 200
                        else f"Image: {caption}"
                    )
                provider = "blip"
            except Exception as e:
                logger.error("All vision tiers failed; last error (%s: %s)", type(e).__name__, e)
                answer = f"Error analyzing image: {str(e)}"
                provider = "none"
        logger.info("Image question answered by %s", provider)
        return ChatResponse(answer=answer, session_id=session_id, provider=provider)

    # Text-only path: llama3
    prompt = f"""You are a helpful teaching assistant. Answer the student's question using ONLY the
lecture content provided below.

{context}

Question: {request.message}

Instructions:
- Answer directly and concisely
- The question may refer back to the conversation so far ("that", "it", "the first one");
  resolve such references using the earlier exchanges before answering
- If the answer is not in the provided content, say
  "I don't see that covered in the lecture materials"
- Do not make up information not present in the content above"""

    fallback = None
    try:
        from providers import generate_text

        result = await generate_text(prompt, max_tokens=600, temperature=0.1, timeout=180.0)
        answer, provider = (
            result.text or "Sorry, I could not generate an answer at this time.",
            result.provider,
        )
        if result.fallback:
            fallback = f"{result.fallback.capitalize()} unavailable: {result.fallback_reason}"
    except Exception as e:
        answer, provider = f"Error connecting to AI: {str(e)}", "none"

    return ChatResponse(answer=answer, session_id=session_id, provider=provider, fallback=fallback)
