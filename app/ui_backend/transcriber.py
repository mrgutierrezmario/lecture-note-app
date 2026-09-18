"""Speech-to-text for one audio chunk at a time (faster-whisper on CPU).

Pipeline per chunk: WebM/Opus → 16 kHz mono WAV via ffmpeg → skip if silent →
Whisper with VAD → filter repetition loops and chunk-boundary duplicates →
segments with timestamps. The model is loaded once per process; work runs in
a small thread pool so the event loop stays responsive.
"""

import asyncio
import logging
import os
import re
import subprocess
import tempfile
import threading
import wave
from collections import Counter, deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from faster_whisper import WhisperModel

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_model = None
_executor = ThreadPoolExecutor(max_workers=2)

RMS_SILENCE_THRESHOLD = 0.008  # skip chunk if RMS below this — pure silence

# Recent segment texts, keyed by session so concurrent recordings never
# suppress each other's speech. Used only to drop chunk-boundary duplicates.
_recent_segments: dict[str, deque[str]] = {}
# Per-session spelling hints for Whisper (lecture title + key terms + the
# server-wide vocabulary), set by the websocket handler on start/reconnect.
_session_prompts: dict[str, str] = {}
_PROMPT_MAX_CHARS = 600  # Whisper reads at most ~224 tokens of prompt
_recent_lock = threading.Lock()
_DEDUP_WINDOW = 4
_MIN_DEDUP_WORDS = 5  # shorter phrases repeat legitimately in lecture speech


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — for equality comparison."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def build_prompt(title: str | None, vocabulary: str | None, global_vocabulary: str = "") -> str:
    """Compose Whisper's ``initial_prompt`` from what we know about the lecture.

    Whisper treats the prompt as preceding text, so a short natural sentence
    that *contains* the terms biases it toward those spellings: "Lecture:
    MGT-699 Strategy. Terms: Porter's five forces, SWOT, Nvidia."
    """
    parts = []
    if title and title.strip():
        parts.append(f"Lecture: {title.strip()}.")
    terms = ", ".join(
        t.strip()
        for src in (global_vocabulary, vocabulary)
        if src
        for t in src.split(",")
        if t.strip()
    )
    if terms:
        parts.append(f"Terms: {terms}.")
    return " ".join(parts)[:_PROMPT_MAX_CHARS]


def set_session_prompt(session_id: str, prompt: str) -> None:
    """Remember the spelling hints for a session (empty string clears them)."""
    if prompt:
        _session_prompts[session_id] = prompt
    else:
        _session_prompts.pop(session_id, None)


def _recent_for(session_id: str | None) -> deque[str]:
    with _recent_lock:
        return _recent_segments.setdefault(session_id or "_default", deque(maxlen=_DEDUP_WINDOW))


def reset_session(session_id: str | None) -> None:
    """Drop dedup history so a new recording starts with a clean slate."""
    with _recent_lock:
        _recent_segments.pop(session_id or "_default", None)


def _is_repetition_loop(text: str) -> bool:
    """True if the text loops on itself — the classic stuck-decoder artifact."""
    clauses = [c.strip() for c in re.split(r"[.!?,;]+", text.lower()) if c.strip()]
    if len(clauses) >= 4 and len(set(clauses)) / len(clauses) < 0.5:
        return True

    words = _normalize(text).split()
    if len(words) >= 12:
        for n in (6, 8):
            ngrams = Counter(" ".join(words[i : i + n]) for i in range(len(words) - n + 1))
            if ngrams.most_common(1)[0][1] > 2:
                return True
    return False


def _is_recent_duplicate(norm: str, recent: deque[str]) -> bool:
    """True if this text already appeared in the last few segments.

    Chunk boundaries re-transcribe overlapping audio, so an exact repeat is
    almost always an artifact. Containment only suppresses a longer phrase that
    adds nothing to one already emitted — never a segment carrying new words.
    """
    is_long = len(norm.split()) >= _MIN_DEDUP_WORDS
    for prev in recent:
        if prev == norm:
            return True
        if is_long and norm in prev:
            return True
    return False


def get_whisper_model() -> WhisperModel:
    """Load the Whisper model on first use and return the shared instance."""
    global _model
    if _model is None:
        logger.info(f"Loading Whisper model: {settings.whisper_model}")
        _model = WhisperModel(
            settings.whisper_model,
            device="cpu",
            compute_type="int8",
        )
        logger.info("Whisper model loaded successfully")
    return _model


def decode_webm_to_wav(webm_data: bytes, output_path: str) -> bool:
    """Convert WebM bytes to a 16 kHz mono PCM WAV file for Whisper.

    Applies a 6 dB gain because browser microphone captures tend to be quiet.
    Returns ``False`` (and logs) on any ffmpeg failure.
    """
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_webm:
        tmp_webm.write(webm_data)
        tmp_webm_path = tmp_webm.name

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                tmp_webm_path,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-af",
                "volume=6dB",
                "-c:a",
                "pcm_s16le",
                output_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg error: {result.stderr.decode()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timed out")
        return False
    except FileNotFoundError:
        logger.error("ffmpeg not found. Please install ffmpeg.")
        return False
    finally:
        if os.path.exists(tmp_webm_path):
            os.unlink(tmp_webm_path)


def get_wav_rms(wav_path: str) -> float:
    """Root-mean-square level of a WAV file (0–1); used to skip silent chunks."""
    with wave.open(wav_path, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(audio**2)))


def transcribe_wav_sync(wav_path: str, session_id: str | None = None) -> list[dict]:
    """Transcribe a WAV file and return clean segments (blocking; run in a thread).

    Each segment is ``{"ts_start", "ts_end", "text"}`` with times relative to
    the chunk. Segments that repeat themselves (a stuck decoder) or repeat a
    recent segment of the same session (boundary overlap) are dropped.
    """
    rms = get_wav_rms(wav_path)
    if rms < RMS_SILENCE_THRESHOLD:
        logger.debug(f"Skipping silent chunk (RMS={rms:.4f})")
        return []

    model = get_whisper_model()
    language = (settings.whisper_language or "en").strip().lower()
    segments, info = model.transcribe(
        wav_path,
        beam_size=5,
        language=None if language == "auto" else language,
        initial_prompt=_session_prompts.get(session_id or "") or None,
        vad_filter=True,
        vad_parameters=dict(threshold=0.5, min_silence_duration_ms=500, speech_pad_ms=200),
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        condition_on_previous_text=False,
        temperature=0.0,
        repetition_penalty=1.1,
    )

    recent = _recent_for(session_id)
    results = []
    for segment in segments:
        text = segment.text.strip()
        norm = _normalize(text)
        if not norm:
            continue
        if _is_repetition_loop(text):
            logger.info(f"Filtered repetition loop: {text!r}")
            continue
        if _is_recent_duplicate(norm, recent):
            logger.info(f"Filtered duplicate of a recent segment: {text!r}")
            continue
        recent.append(norm)
        results.append(
            {
                "ts_start": segment.start,
                "ts_end": segment.end,
                "text": text,
            }
        )
    return results


async def transcribe_chunk(
    webm_data: bytes, session_id: str | None = None
) -> tuple[bool, bool, list[dict], str | None]:
    """Decode and transcribe one chunk off the event loop.

    Returns ``(decode_ok, transcribed_ok, segments, error)`` so the caller can
    record exactly which step failed on the chunk row.
    """
    loop = asyncio.get_event_loop()

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
        wav_path = tmp_wav.name

    try:
        decode_ok = await loop.run_in_executor(
            _executor,
            decode_webm_to_wav,
            webm_data,
            wav_path,
        )

        if not decode_ok:
            return False, False, [], "Failed to decode webm to wav"

        segments = await loop.run_in_executor(
            _executor,
            transcribe_wav_sync,
            wav_path,
            session_id,
        )

        return True, True, segments, None

    except Exception as e:
        logger.exception("Transcription error")
        return True, False, [], str(e)
    finally:
        if os.path.exists(wav_path):
            os.unlink(wav_path)
