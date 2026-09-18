"""Validation of runtime settings overrides."""

import pytest

import settings_store as ss


def test_masked():
    assert ss.masked(None) is None
    assert ss.masked("sk-abcdef1234") == "...1234"


def test_update_overrides_validates():
    with pytest.raises(ValueError):
        ss.update_overrides({"no_such_setting": 1})
    with pytest.raises(ValueError):
        ss.update_overrides({"notes_interval_seconds": 5})
    with pytest.raises(ValueError):
        ss.update_overrides({"audio_retention_days": 0})
    with pytest.raises(ValueError):
        ss.update_overrides({"gemini_model": "   "})


def test_update_overrides_applies_live_and_allows_empty_where_meant():
    applied, restart = ss.update_overrides(
        {"notes_interval_seconds": 120, "google_client_id": "", "whisper_vocabulary": ""}
    )
    assert applied["notes_interval_seconds"] == 120
    assert ss.get_settings().notes_interval_seconds == 120
    assert applied["google_client_id"] == ""
    assert restart == []


def test_whisper_model_needs_restart():
    _, restart = ss.update_overrides({"whisper_model": "tiny"})
    assert restart == ["whisper_model"]
