"""The application version, read from the repository's ``VERSION`` file.

One file is the source of truth for the backend, the frontend build (Vite
reads it too) and the git tag / GitHub release. It sits at the repository
root in a checkout and at ``/app/VERSION`` in the Docker image, so it is
found by walking up from this module.
"""

from pathlib import Path

FALLBACK = "0.0.0"


def read_version() -> str:
    """The contents of the nearest ``VERSION`` file above this module."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "VERSION"
        if candidate.is_file():
            return candidate.read_text().strip() or FALLBACK
    return FALLBACK


__version__ = read_version()
