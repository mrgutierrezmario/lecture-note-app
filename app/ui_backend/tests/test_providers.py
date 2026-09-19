"""Provider cascade order and failure descriptions."""

from ai import providers as p


def test_cloud_cascade_prefers_primary_then_other_configured(monkeypatch):
    monkeypatch.setattr(p, "configured", lambda name: name in ("gemini", "claude"))
    assert p._cloud_cascade("gemini", ("gemini", "claude", "openai")) == ["gemini", "claude"]
    assert p._cloud_cascade("claude", ("gemini", "claude", "openai")) == ["claude", "gemini"]
    # Local models are never part of the cloud cascade.
    assert "ollama" not in p._cloud_cascade("gemini", ("gemini", "ollama", "llava"))


def test_describe_failure_is_human():
    assert "quota" in p.describe_failure(
        Exception("429 RESOURCE_EXHAUSTED quota")
    ).lower() or "429" in p.describe_failure(Exception("429 RESOURCE_EXHAUSTED quota"))
    text = p.describe_failure(Exception("credit balance is too low"))
    assert "credit" in text.lower()
