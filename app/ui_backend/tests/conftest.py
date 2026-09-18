"""Test setup: an isolated STATE_DIR, a fixed SECRET_KEY, no outgoing mail, and
a stand-in for faster-whisper so the suite runs without the model libraries.

Everything under ``tests/`` is pure-Python: no Postgres, MinIO or Ollama are
needed. Anything that would touch them is exercised through the API smoke
tests, which assert the *shape* of failure (503 from /health), not success.
"""

import os
import sys
import tempfile
import types
from pathlib import Path

# Import the backend modules by their plain names, as the app itself does.
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_state = tempfile.mkdtemp(prefix="lecture-tests-")
os.environ.setdefault("STATE_DIR", _state)
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("PUBLIC_URL", "https://notes.example.test")
for var in ("MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_FROM", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
    os.environ.pop(var, None)
os.environ["POSTGRES_HOST"] = "127.0.0.1"
os.environ["POSTGRES_PORT"] = "1"  # nothing listens: DB checks must fail fast, not hang

# faster-whisper (and its native libraries) are not needed to test the logic
# around transcription; give the transcriber module something to import.
if "faster_whisper" not in sys.modules:
    fake = types.ModuleType("faster_whisper")

    class WhisperModel:
        """Stand-in that refuses to load: no test may transcribe for real."""

        def __init__(self, *args, **kwargs):
            """Fail loudly if anything tries to build the model."""
            raise RuntimeError("WhisperModel is not available in tests")

    fake.WhisperModel = WhisperModel
    sys.modules["faster_whisper"] = fake
