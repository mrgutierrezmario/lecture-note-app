"""Admin settings API: models, provider choice, API keys, limits.

Non-secret values persist through ``settings_store`` (a JSON overrides file);
API keys go to ``STATE_DIR/.env`` and are only ever returned masked.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException

from accounts.auth import CurrentUser, current_user, require_admin
from ai import providers
from core import settings_store
from core.config import get_settings
from core.schemas import AuthStatus, ModelOption, ProviderTest, SettingsResponse, SettingsUpdate
from integrations import google_drive, mailer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def admin_or_demo(user: CurrentUser = Depends(current_user)) -> CurrentUser:
    """Admins manage settings; the demo account may *look* (a reduced,
    read-only view — see ``read_settings``)."""
    if not (user.is_admin or user.is_demo):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# Fields the panel can change that are not the secret key.
_OVERRIDE_FIELDS = (
    "vision_model",
    "ollama_model",
    "whisper_model",
    "notes_interval_seconds",
    "storage_quota_mb",
    "registration_open",
    "registration_approval",
    "max_locked_lectures",
    "text_provider",
    "vision_provider",
    "claude_text_model",
    "gemini_model",
    "openai_model",
    "google_client_id",
    "google_picker_api_key",
    "audio_retention_days",
    "whisper_language",
    "whisper_vocabulary",
)


async def _ollama_reachable(base_url: str) -> bool:
    """Whether Ollama answers where the config points — the default localhost is
    wrong whenever Ollama runs in a sibling container, and that failure is
    otherwise invisible until notes generation silently degrades."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(f"{base_url}/api/tags")
            return response.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


async def _current(restart_required: list[str] | None = None) -> SettingsResponse:
    """Report the value that *will* be in effect, plus which fields need a restart.

    A field that only applies on restart (whisper_model) is saved but not applied,
    so the live settings object still holds the old value. Reporting that value
    would make the panel snap back to it right after a save. Report the saved
    value instead and derive restart_required by comparing the two — so a page
    reload still shows the pending state, not just the response to the PUT.
    """
    settings = get_settings()
    pending = settings_store.pending_restart_values()
    restart_required = list(restart_required or [])
    for name in pending:
        if name not in restart_required:
            restart_required.append(name)

    def value(name: str):
        return pending.get(name, getattr(settings, name))

    return SettingsResponse(
        auth=AuthStatus(**settings_store.auth_status()),
        vision_model=value("vision_model"),
        ollama_model=value("ollama_model"),
        whisper_model=value("whisper_model"),
        notes_interval_seconds=value("notes_interval_seconds"),
        storage_quota_mb=value("storage_quota_mb"),
        audio_retention_days=value("audio_retention_days"),
        whisper_language=value("whisper_language"),
        whisper_vocabulary=value("whisper_vocabulary"),
        registration_open=value("registration_open"),
        registration_approval=value("registration_approval"),
        mail_configured=mailer.configured(),
        max_locked_lectures=value("max_locked_lectures"),
        text_provider=value("text_provider"),
        active_text_provider=providers.active_provider(),
        vision_provider=value("vision_provider"),
        active_vision_provider=providers.active_vision_provider(),
        claude_text_model=value("claude_text_model"),
        gemini_model=value("gemini_model"),
        gemini_key_masked=settings_store.masked(settings.gemini_api_key),
        openai_model=value("openai_model"),
        openai_key_masked=settings_store.masked(settings.openai_api_key),
        google_client_id=settings.google_client_id,
        google_picker_api_key=settings.google_picker_api_key,
        google_client_secret_masked=settings_store.masked(settings.google_client_secret),
        google_redirect_uri=google_drive.redirect_uri(),
        ollama_base_url=settings.ollama_base_url,
        ollama_reachable=await _ollama_reachable(settings.ollama_base_url),
        restart_required=restart_required,
    )


@router.get("", response_model=SettingsResponse)
async def read_settings(user: CurrentUser = Depends(admin_or_demo)):
    """Current settings for the panel. The demo account gets the same shape
    with anything secret-adjacent blanked (key previews, OAuth client)."""
    current = await _current()
    if user.is_demo:
        current.auth = AuthStatus(
            source="none",
            detail="",
            key_masked=None,
            profile_on_disk=False,
            sdk_version=current.auth.sdk_version,
            sdk_supports_profiles=current.auth.sdk_supports_profiles,
            warnings=[],
        )
        current.gemini_key_masked = None
        current.openai_key_masked = None
        current.google_client_id = ""
        current.google_client_secret_masked = None
        current.google_picker_api_key = ""
    return current


@router.put("", response_model=SettingsResponse, dependencies=[Depends(require_admin)])
async def write_settings(update: SettingsUpdate):
    """Apply a partial update. Keys are stored separately from the other
    fields; ``restart_required`` in the reply lists fields that only take
    effect after a backend restart (currently the Whisper model).
    """
    # The key is handled separately from the rest: it is a secret, so it goes to
    # .env rather than the overrides file. An empty string is a deliberate clear;
    # None means "not part of this request".
    if update.anthropic_api_key is not None:
        settings_store.set_api_key(update.anthropic_api_key)
    if update.gemini_api_key is not None:
        settings_store.set_secret("GEMINI_API_KEY", update.gemini_api_key)
    if update.openai_api_key is not None:
        settings_store.set_secret("OPENAI_API_KEY", update.openai_api_key)
    if update.google_client_secret is not None:
        settings_store.set_secret("GOOGLE_CLIENT_SECRET", update.google_client_secret)
    if update.text_provider is not None and update.text_provider not in providers.PROVIDERS:
        raise HTTPException(
            status_code=422, detail=f"text_provider must be one of {', '.join(providers.PROVIDERS)}"
        )
    if (
        update.vision_provider is not None
        and update.vision_provider not in providers.VISION_PROVIDERS
    ):
        raise HTTPException(
            status_code=422,
            detail=f"vision_provider must be one of {', '.join(providers.VISION_PROVIDERS)}",
        )

    overrides = {f: getattr(update, f) for f in _OVERRIDE_FIELDS}
    overrides = {k: v for k, v in overrides.items() if v is not None}

    restart_required: list[str] = []
    if overrides:
        try:
            _, restart_required = settings_store.update_overrides(overrides)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

    return await _current(restart_required)


@router.post(
    "/test-provider/{provider}", response_model=ProviderTest, dependencies=[Depends(require_admin)]
)
async def test_provider(provider: str):
    """Cheap connectivity check for one AI provider (uses the saved key)."""
    if provider not in providers.PROVIDERS and provider not in providers.VISION_PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown provider")
    if provider == "llava":
        provider = "ollama"
    ok, detail = await providers.test_provider(provider)
    return ProviderTest(provider=provider, ok=ok, detail=detail)


@router.get(
    "/gemini-models", response_model=list[ModelOption], dependencies=[Depends(require_admin)]
)
async def gemini_models():
    """Chat-capable Gemini models available to the saved key, from Google's live list."""
    try:
        return await providers.list_gemini_models()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)[:200]) from e
