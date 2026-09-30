"""Whisper spelling hints built from per-lecture terms and the global list."""

from ai import transcriber as t


def test_build_prompt_composes_all_sources():
    p = t.build_prompt(" Porter,SWOT , Nvidia ", "Prof. Ramirez, HBR")
    assert p == "Terms: Prof. Ramirez, HBR, Porter, SWOT, Nvidia."


def test_build_prompt_handles_missing_parts():
    assert t.build_prompt(None) == ""
    assert t.build_prompt("", "") == ""
    assert t.build_prompt("a, b") == "Terms: a, b."


def test_build_prompt_is_bounded():
    assert len(t.build_prompt(", ".join(["term"] * 500))) <= t._PROMPT_MAX_CHARS


def test_session_prompt_set_and_clear():
    t.set_session_prompt("s1", "Terms: A.", "BIA568-09-30-26")
    assert t._session_prompts["s1"] == "Terms: A."
    assert t._session_titles["s1"] == "BIA568-09-30-26"
    t.set_session_prompt("s1", "")
    assert "s1" not in t._session_prompts
    assert "s1" not in t._session_titles
