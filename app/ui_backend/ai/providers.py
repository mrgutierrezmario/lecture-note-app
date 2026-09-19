"""Text generation behind one call, with the provider chosen in Settings.

``generate_text`` serves notes and chat. ``text_provider`` picks Ollama (local,
default), Gemini or OpenAI; a cloud failure (bad key, quota, outage) falls back
to Ollama so a lecture never loses its notes. Keys live in STATE_DIR/.env next
to the Anthropic key. Plain HTTP via httpx — no extra SDKs.
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx

from core.config import get_settings

logger = logging.getLogger(__name__)

PROVIDERS = ("ollama", "claude", "gemini", "openai")
VISION_PROVIDERS = ("claude", "gemini", "openai", "llava")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


class ProviderError(Exception):
    """A provider refused or failed a request (bad key, quota, outage, empty reply)."""


# Newer Gemini Flash models "think" before answering and bill it against
# maxOutputTokens, so a small budget returns nothing. We turn thinking off, but
# the accepted knob differs per model, so probe once and remember per model.
_THINKING_OPTIONS = (
    {"thinkingConfig": {"thinkingLevel": "MINIMAL"}},
    {"thinkingConfig": {"thinkingBudget": 0}},
    {},
)
_gemini_thinking_cfg: dict[str, dict] = {}


async def _gemini_call(
    client: httpx.AsyncClient, model: str, parts: list, max_tokens: int, temperature: float
) -> dict:
    """POST generateContent, negotiating the thinking config and retrying once on 503/429."""
    url = GEMINI_URL.format(model=model)
    headers = {"x-goog-api-key": key_for("gemini")}
    options = (
        [_gemini_thinking_cfg[model]] if model in _gemini_thinking_cfg else list(_THINKING_OPTIONS)
    )
    last = None
    for cfg in options:
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens, **cfg},
        }
        for attempt in (1, 2):
            r = await client.post(url, headers=headers, json=body)
            if r.status_code in (503, 429) and attempt == 1:
                await asyncio.sleep(2)
                continue
            break
        if (
            r.status_code == 400
            and cfg
            and "thinking" in r.text.lower()
            or (r.status_code == 400 and cfg and "invalid argument" in r.text.lower())
        ):
            last = r
            continue  # this model doesn't take that knob; try the next
        if r.status_code != 200:
            raise ProviderError(f"Gemini error {r.status_code}: {r.text[:300]}")
        _gemini_thinking_cfg[model] = cfg
        return r.json()
    raise ProviderError(
        f"Gemini error {last.status_code if last else '?'}: "
        f"{last.text[:300] if last else 'no response'}"
    )


def _gemini_text(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        text = ""
    if not text:
        reason = (data.get("candidates") or [{}])[0].get("finishReason") or data.get(
            "promptFeedback", {}
        ).get("blockReason")
        raise ProviderError(f"Gemini returned no text (reason: {reason})")
    return text


@dataclass
class Generation:
    """A text result and the ``provider/model`` label that produced it.

    When a cloud provider failed and Ollama answered instead, ``fallback``
    names the provider that failed and ``fallback_reason`` says why, in plain
    words for the UI.
    """

    text: str
    provider: str  # e.g. "gemini/gemini-2.5-flash", "ollama/llama3"
    fallback: str | None = None  # e.g. "gemini"
    fallback_reason: str | None = None  # e.g. "quota or rate limit exceeded"


def describe_failure(exc: Exception) -> str:
    """Turn a provider exception into a short reason a user can act on."""
    msg = str(exc)
    low = msg.lower()
    if "429" in msg or "quota" in low or "rate" in low:
        return "quota or rate limit exceeded"
    if "503" in msg or "overloaded" in low or "high demand" in low:
        return "temporarily overloaded"
    if "credit" in low:
        return "no API credits"
    if "401" in msg or "403" in msg or "api key" in low or "permission_denied" in low:
        return "API key rejected"
    if "404" in msg or "not found" in low:
        return "model not available"
    if "timeout" in low or "timed out" in low:
        return "timed out"
    return "unavailable"


def key_for(provider: str) -> str:
    """The saved API key for a cloud provider (empty string if none)."""
    s = get_settings()
    return {
        "claude": s.anthropic_api_key or "",
        "gemini": s.gemini_api_key or "",
        "openai": s.openai_api_key or "",
    }.get(provider, "")


def configured(provider: str) -> bool:
    """Whether a provider can be used right now (local ones always can)."""
    if provider in ("ollama", "llava"):
        return True
    if provider == "claude":
        from core import settings_store

        return settings_store.credentials_available()
    return bool(key_for(provider))


def active_vision_provider() -> str:
    """The cloud vision provider images will try first ('llava' = local only)."""
    chosen = get_settings().vision_provider
    if chosen in VISION_PROVIDERS and configured(chosen):
        return chosen
    if chosen != "llava":
        logger.warning("vision_provider=%s has no API key; using llava", chosen)
    return "llava"


def _anthropic_client():
    """Client without forcing api_key: the SDK also honours ANTHROPIC_AUTH_TOKEN
    and OAuth profiles; an explicit empty key would shadow those."""
    import os

    import anthropic

    key = (get_settings().anthropic_api_key or "").strip()
    headers = {}
    if not key and os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        headers["anthropic-beta"] = "oauth-2025-04-20"
    kwargs = {"default_headers": headers} if headers else {}
    if key:
        kwargs["api_key"] = key
    return anthropic.AsyncAnthropic(**kwargs)


def active_provider() -> str:
    """The provider notes/chat will actually use right now."""
    chosen = get_settings().text_provider
    if chosen in PROVIDERS and configured(chosen):
        return chosen
    if chosen != "ollama":
        logger.warning("text_provider=%s has no API key; using ollama", chosen)
    return "ollama"


async def _ollama(prompt: str, max_tokens: int, temperature: float, timeout: float) -> Generation:
    s = get_settings()
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{s.ollama_base_url}/api/generate",
            json={
                "model": s.ollama_model,
                "prompt": prompt,
                "stream": False,
                # num_ctx: Ollama defaults to ~2k tokens, which would silently
                # truncate the lecture context; 8k fits the transcript window.
                "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": 8192},
            },
        )
    if r.status_code != 200:
        raise ProviderError(f"Ollama error {r.status_code}: {r.text[:200]}")
    return Generation(r.json().get("response", "").strip(), f"ollama/{s.ollama_model}")


async def _claude(prompt: str, max_tokens: int, temperature: float, timeout: float) -> Generation:
    s = get_settings()
    client = _anthropic_client()
    response = await client.with_options(timeout=timeout).messages.create(
        model=s.claude_text_model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(getattr(b, "text", "") for b in response.content).strip()
    return Generation(text, f"claude/{s.claude_text_model}")


async def _gemini(prompt: str, max_tokens: int, temperature: float, timeout: float) -> Generation:
    s = get_settings()
    async with httpx.AsyncClient(timeout=timeout) as client:
        data = await _gemini_call(
            client, s.gemini_model, [{"text": prompt}], max(max_tokens, 2048), temperature
        )
    return Generation(_gemini_text(data), f"gemini/{s.gemini_model}")


async def _openai(prompt: str, max_tokens: int, temperature: float, timeout: float) -> Generation:
    s = get_settings()
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {key_for('openai')}"},
            json={
                "model": s.openai_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
            },
        )
    if r.status_code != 200:
        raise ProviderError(f"OpenAI error {r.status_code}: {r.text[:300]}")
    try:
        text = r.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise ProviderError("OpenAI returned no text") from None
    return Generation(text, f"openai/{s.openai_model}")


_IMPL = {"ollama": _ollama, "claude": _claude, "gemini": _gemini, "openai": _openai}


# ── Vision ────────────────────────────────────────────────────────────────────


async def _claude_image(b64: str, media_type: str, prompt: str, max_tokens: int) -> str:
    s = get_settings()
    client = _anthropic_client()
    response = await client.messages.create(
        model=s.vision_model,
        max_tokens=max_tokens,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": b64},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )
    return "".join(getattr(b, "text", "") for b in response.content).strip()


async def _gemini_image(b64: str, media_type: str, prompt: str, max_tokens: int) -> str:
    s = get_settings()
    parts = [{"inline_data": {"mime_type": media_type, "data": b64}}, {"text": prompt}]
    async with httpx.AsyncClient(timeout=120.0) as client:
        data = await _gemini_call(client, s.gemini_model, parts, max(max_tokens, 2048), 0.1)
    return _gemini_text(data)


async def _openai_image(b64: str, media_type: str, prompt: str, max_tokens: int) -> str:
    s = get_settings()
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {key_for('openai')}"},
            json={
                "model": s.openai_model,
                "max_completion_tokens": max_tokens,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{media_type};base64,{b64}"},
                            },
                        ],
                    }
                ],
            },
        )
    if r.status_code != 200:
        raise ProviderError(f"OpenAI error {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"].strip()


_VISION_IMPL = {"claude": _claude_image, "gemini": _gemini_image, "openai": _openai_image}


def _cloud_cascade(primary: str, order: tuple[str, ...]) -> list[str]:
    """The primary provider first, then every other configured cloud provider.

    So a Gemini quota failure tries Claude (if a key is saved) before giving up
    on the cloud — the user chooses the first; the rest are backups.
    """
    rest = [p for p in order if p != primary and p not in ("ollama", "llava") and configured(p)]
    return [primary] + rest


async def describe_image_cloud(
    b64: str, media_type: str, prompt: str, max_tokens: int = 1024
) -> tuple[str, str]:
    """(text, provider label) from the chosen cloud vision provider, trying the
    other configured cloud providers if it fails; raises when none is
    configured or all fail — callers then fall back to llava/BLIP."""
    provider = active_vision_provider()
    if provider == "llava":
        raise ProviderError("No cloud vision provider configured")
    s = get_settings()
    models = {"claude": s.vision_model, "gemini": s.gemini_model, "openai": s.openai_model}
    last: Exception | None = None
    for candidate in _cloud_cascade(provider, ("gemini", "claude", "openai")):
        try:
            text = await _VISION_IMPL[candidate](b64, media_type, prompt, max_tokens)
            if candidate != provider:
                logger.info("Vision: %s answered after %s failed", candidate, provider)
            return text, f"{candidate}/{models[candidate]}"
        except Exception as e:  # noqa: BLE001 — try the next provider
            last = e
            logger.warning("%s vision failed (%s: %s)", candidate, type(e).__name__, str(e)[:200])
    raise ProviderError(f"All cloud vision providers failed: {last}")


async def generate_text(
    prompt: str, *, max_tokens: int = 800, temperature: float = 0.1, timeout: float = 120.0
) -> Generation:
    """Generate with the configured provider.

    A cloud failure tries the other configured cloud providers, then Ollama,
    so notes never stop. The returned ``Generation`` records the first
    provider that failed and why, for the UI.
    """
    provider = active_provider()
    if provider == "ollama":
        return await _ollama(prompt, max_tokens, temperature, timeout)

    first_error: Exception | None = None
    for candidate in _cloud_cascade(provider, ("gemini", "claude", "openai")):
        try:
            result = await _IMPL[candidate](prompt, max_tokens, temperature, timeout)
            if candidate != provider:
                result.fallback = provider
                result.fallback_reason = describe_failure(first_error)
            return result
        except Exception as e:  # noqa: BLE001 — try the next provider
            first_error = first_error or e
            logger.warning(
                "%s failed (%s: %s) — trying next provider",
                candidate,
                type(e).__name__,
                str(e)[:200],
            )
    result = await _ollama(prompt, max_tokens, temperature, timeout)
    result.fallback = provider
    result.fallback_reason = describe_failure(first_error)
    return result


async def test_provider(provider: str) -> tuple[bool, str]:
    """Cheap connectivity check used by the Settings panel."""
    if not configured(provider):
        return False, "No API key saved"
    try:
        g = await _IMPL[provider]("Reply with the single word OK.", 5, 0.0, 30.0)
        return True, f"Connected ({g.provider})"
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:200]}"


# ── Model discovery ───────────────────────────────────────────────────────────

_EXCLUDE = (
    "image",
    "tts",
    "customtools",
    "deep-research",
    "lyria",
    "omni",
    "embedding",
    "aqa",
    "live",
    "audio",
)


async def list_gemini_models() -> list[dict]:
    """Chat-capable Gemini models this key can use, newest first, from Google's
    live list — so the Settings dropdown never goes stale."""
    if not key_for("gemini"):
        raise ProviderError("No Gemini API key saved")
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": key_for("gemini")},
            params={"pageSize": 200},
        )
    if r.status_code != 200:
        raise ProviderError(f"Gemini error {r.status_code}: {r.text[:200]}")
    out = []
    for m in r.json().get("models", []):
        name = m.get("name", "").replace("models/", "")
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        if not name.startswith("gemini-") or not ("flash" in name or "pro" in name):
            continue
        if any(x in name for x in _EXCLUDE):
            continue
        out.append({"id": name, "label": m.get("displayName") or name})

    # Aliases first (they auto-track the newest release), then newest version numbers.
    def sort_key(item):
        n = item["id"]
        if "latest" in n:
            return (0, n)
        import re

        v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return (1, -float(v.group(1)) if v else 0, "preview" in n, n)

    out.sort(key=sort_key)
    return out
