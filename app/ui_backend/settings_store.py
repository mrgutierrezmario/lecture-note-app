"""Runtime-editable settings and credential detection for the settings panel.

Two kinds of state live here:

- **Non-secret overrides** (models, intervals) persist to ``runtime_settings.json``
  and are applied by mutating the cached ``Settings`` instance. Every module does
  ``settings = get_settings()`` at import time and ``get_settings`` is
  ``lru_cache``d, so they all hold the *same* object — mutating an attribute on it
  is visible everywhere immediately. Rebinding via ``cache_clear()`` would not be:
  the old object would stay referenced by those modules.
- **The Anthropic key** is a secret, so it never enters the JSON file. It is
  written to ``.env`` (mode 0600) and mirrored into ``os.environ`` plus the live
  settings object. It is never returned by the API — only a masked preview.

``whisper_model`` is the exception to live application: ``transcriber`` loads the
model once into a module global, so a change there needs a restart. The API says
so in ``restart_required`` rather than pretending otherwise.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from config import STATE_DIR, get_settings

logger = logging.getLogger(__name__)

RUNTIME_PATH = STATE_DIR / "runtime_settings.json"
ENV_PATH = STATE_DIR / ".env"

KEY_ENV_VAR = "ANTHROPIC_API_KEY"
TOKEN_ENV_VAR = "ANTHROPIC_AUTH_TOKEN"

# Editable non-secret fields: name -> (type, applies_live)
EDITABLE: dict[str, tuple[type, bool]] = {
    "vision_model": (str, True),
    "ollama_model": (str, True),
    "notes_interval_seconds": (int, True),
    "whisper_model": (str, False),
    "storage_quota_mb": (int, True),
    "registration_open": (bool, True),
    "max_locked_lectures": (int, True),
    "text_provider": (str, True),
    "vision_provider": (str, True),
    "claude_text_model": (str, True),
    "gemini_model": (str, True),
    "openai_model": (str, True),
}

# Secrets kept in STATE_DIR/.env rather than the overrides file: env var -> settings attr.
SECRET_FIELDS = {
    "ANTHROPIC_API_KEY": "anthropic_api_key",
    "GEMINI_API_KEY": "gemini_api_key",
    "OPENAI_API_KEY": "openai_api_key",
}


# ── Non-secret overrides ──────────────────────────────────────────────────────


def _read_overrides() -> dict[str, Any]:
    if not RUNTIME_PATH.exists():
        return {}
    try:
        data = json.loads(RUNTIME_PATH.read_text())
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Ignoring unreadable %s: %s", RUNTIME_PATH.name, e)
        return {}


def _write_overrides(overrides: dict[str, Any]) -> None:
    RUNTIME_PATH.write_text(json.dumps(overrides, indent=2, sort_keys=True) + "\n")


def _restore_secrets_from_env_file() -> None:
    """Make keys saved by the Settings panel win over *empty* env vars.

    Container runtimes commonly pass ``VAR=""`` when a variable is declared but
    unset; pydantic-settings then prefers that empty value over the key in
    STATE_DIR/.env, and the SDK would authenticate with an empty key.
    """
    settings = get_settings()
    saved: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() in SECRET_FIELDS and value.strip():
                saved[name.strip()] = value.strip()
    for env_var, attr in SECRET_FIELDS.items():
        if getattr(settings, attr):
            continue
        os.environ.pop(env_var, None)
        if env_var in saved:
            os.environ[env_var] = saved[env_var]
            setattr(settings, attr, saved[env_var])
            logger.info("%s restored from %s", env_var, ENV_PATH.name)


def apply_persisted_overrides() -> dict[str, Any]:
    """Re-apply saved overrides onto the live settings object. Call on startup."""
    _restore_secrets_from_env_file()
    overrides = _read_overrides()
    settings = get_settings()
    applied = {}
    for name, value in overrides.items():
        if name not in EDITABLE:
            continue
        expected, _ = EDITABLE[name]
        try:
            setattr(settings, name, expected(value))
            applied[name] = getattr(settings, name)
        except (TypeError, ValueError) as e:
            logger.warning("Skipping saved override %s=%r: %s", name, value, e)
    if applied:
        logger.info("Applied saved settings overrides: %s", applied)
    return applied


def update_overrides(updates: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate, persist, and apply overrides.

    Returns (applied, restart_required_fields).
    """
    settings = get_settings()
    overrides = _read_overrides()
    applied: dict[str, Any] = {}
    restart_required: list[str] = []

    for name, raw in updates.items():
        if raw is None:
            continue
        if name not in EDITABLE:
            raise ValueError(f"Unknown setting: {name}")
        expected, live = EDITABLE[name]
        try:
            value = expected(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be {expected.__name__}")
        if expected is str and not value.strip():
            raise ValueError(f"{name} must not be empty")
        if name == "notes_interval_seconds" and value < 10:
            raise ValueError("notes_interval_seconds must be at least 10")

        overrides[name] = value
        applied[name] = value
        if live:
            setattr(settings, name, value)
        else:
            # Persisted and picked up on next boot; the loaded model stays put.
            restart_required.append(name)

    _write_overrides(overrides)
    if applied:
        logger.info(
            "Settings updated: %s (restart required: %s)", applied, restart_required or "none"
        )
    return applied, restart_required


# ── Anthropic key (secret) ────────────────────────────────────────────────────


def _rewrite_env_key(env_var: str, key: Optional[str]) -> None:
    """Set or remove one ``VAR=`` line in .env, preserving everything else.

    Removing means deleting the line outright, never writing ``VAR=``. An empty
    value still occupies its slot in the SDK's credential precedence and would
    authenticate with an empty key, shadowing any OAuth token.
    """
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    kept = [ln for ln in lines if not ln.strip().startswith(f"{env_var}=")]
    if key:
        kept.append(f"{env_var}={key}")
    text = "\n".join(kept).rstrip("\n") + "\n"
    ENV_PATH.write_text(text)
    try:
        ENV_PATH.chmod(0o600)
    except OSError as e:
        logger.warning("Could not tighten permissions on .env: %s", e)


def set_secret(env_var: str, key: Optional[str]) -> None:
    """Store (or clear) an API key in .env, os.environ and live settings."""
    attr = SECRET_FIELDS[env_var]
    key = (key or "").strip() or None
    _rewrite_env_key(env_var, key)
    if key:
        os.environ[env_var] = key
    else:
        os.environ.pop(env_var, None)
    setattr(get_settings(), attr, key)
    logger.info("%s %s", env_var, "set" if key else "cleared")


def set_api_key(key: Optional[str]) -> None:
    """Store or clear the Anthropic API key (shorthand for ``set_secret``)."""
    set_secret(KEY_ENV_VAR, key)


def masked(key: Optional[str]) -> Optional[str]:
    """The last four characters of a key for display, or ``None`` if unset."""
    return f"...{key[-4:]}" if key else None


# ── Credential detection ──────────────────────────────────────────────────────


def _sdk_supports_profiles() -> tuple[bool, str]:
    """Profile/OAuth resolution landed in the 1.x SDK line; 0.x cannot read it."""
    try:
        import anthropic

        version = getattr(anthropic, "__version__", "unknown")
    except ImportError:
        return False, "not installed"
    major = version.split(".", 1)[0]
    return (major.isdigit() and int(major) >= 1), version


def _profile_on_disk() -> bool:
    config_dir = os.environ.get("ANTHROPIC_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path.home() / ".config" / "anthropic"
    creds = base / "credentials"
    return creds.is_dir() and any(creds.glob("*.json"))


def credentials_available() -> bool:
    """True when the Anthropic SDK has some credential it can actually use."""
    status = auth_status()
    return status["source"] in ("api_key", "auth_token", "profile")


def auth_status() -> dict[str, Any]:
    """Report which credential the SDK would actually use, and any misconfiguration.

    Precedence mirrors the SDK: ANTHROPIC_API_KEY, then ANTHROPIC_AUTH_TOKEN, then
    an on-disk OAuth profile (1.x SDKs only).
    """
    # Two independent places a key can come from, with different failure modes:
    # an exported env var (which the SDK reads directly and where an empty value
    # is a real trap) and the .env file (which only reaches us via pydantic, and
    # whose empty value is merely untidy — but would break the client if passed
    # through as an explicit api_key="").
    env_key = os.environ.get(KEY_ENV_VAR)
    dotenv_key = get_settings().anthropic_api_key
    token = os.environ.get(TOKEN_ENV_VAR) or None

    env_key_empty = env_key is not None and not env_key.strip()
    dotenv_key_empty = dotenv_key is not None and not dotenv_key.strip()

    raw_key = env_key if (env_key and env_key.strip()) else (dotenv_key or None)
    key_usable = bool(raw_key and raw_key.strip())
    key_empty = env_key_empty and not key_usable

    supports_profiles, sdk_version = _sdk_supports_profiles()
    profile_on_disk = _profile_on_disk()

    warnings: list[str] = []
    if env_key_empty:
        warnings.append(
            f"{KEY_ENV_VAR} is exported but empty. An empty value still wins the "
            "SDK's credential precedence and authenticates as an empty key — unset "
            "it entirely instead of blanking it."
        )
    elif dotenv_key_empty:
        warnings.append(
            f"{KEY_ENV_VAR}= is present but empty in .env. It never reaches the "
            "environment, so the SDK ignores it, but remove the line rather than "
            "blanking it so nothing passes an empty key through explicitly."
        )
    if key_usable and token:
        warnings.append(
            f"Both {KEY_ENV_VAR} and {TOKEN_ENV_VAR} are set. The SDK sends both and "
            "the API rejects the request — clear one."
        )
    if profile_on_disk and not supports_profiles:
        warnings.append(
            f"An OAuth profile exists on disk but the installed anthropic SDK "
            f"({sdk_version}) cannot read it — profile resolution needs 1.x. Bridge it "
            f"with `ant auth print-credentials --env` to set {TOKEN_ENV_VAR}, or upgrade."
        )
    if profile_on_disk and supports_profiles and key_usable:
        warnings.append(
            f"An OAuth profile exists but {KEY_ENV_VAR} takes precedence, so the "
            "profile is ignored."
        )

    if key_usable:
        source, detail = "api_key", "Using ANTHROPIC_API_KEY"
    elif key_empty:
        source, detail = "misconfigured", f"{KEY_ENV_VAR} is set to an empty value"
    elif token:
        source, detail = "auth_token", f"Using {TOKEN_ENV_VAR} (short-lived OAuth token)"
    elif profile_on_disk and supports_profiles:
        source, detail = "profile", "Using OAuth profile from ant auth login"
    else:
        source, detail = "none", "No Anthropic credentials — image analysis uses local models"

    return {
        "source": source,
        "detail": detail,
        "key_masked": f"...{raw_key.strip()[-4:]}"
        if key_usable and len(raw_key.strip()) >= 4
        else None,
        "profile_on_disk": profile_on_disk,
        "sdk_version": sdk_version,
        "sdk_supports_profiles": supports_profiles,
        "warnings": warnings,
    }


def pending_restart_values() -> dict[str, Any]:
    """Saved overrides that are not yet live, i.e. awaiting a restart.

    Only non-live fields can be pending; live ones are applied on write, and on
    boot ``apply_persisted_overrides`` makes everything match again.
    """
    settings = get_settings()
    pending = {}
    for name, value in _read_overrides().items():
        spec = EDITABLE.get(name)
        if spec is None or spec[1]:
            continue
        expected = spec[0]
        try:
            saved = expected(value)
        except (TypeError, ValueError):
            continue
        if saved != getattr(settings, name):
            pending[name] = saved
    return pending
