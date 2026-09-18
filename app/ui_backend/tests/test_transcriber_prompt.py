"""Whisper spelling hints built from title, per-lecture terms and the global list."""

import transcriber as t


def test_build_prompt_composes_all_sources():
    p = t.build_prompt("MGT-699 Strategy", " Porter,SWOT , Nvidia ", "Prof. Ramirez, HBR")
    assert p == "Lecture: MGT-699 Strategy. Terms: Prof. Ramirez, HBR, Porter, SWOT, Nvidia."


def test_build_prompt_handles_missing_parts():
    assert t.build_prompt(None, None) == ""
    assert t.build_prompt("Title only", "") == "Lecture: Title only."
    assert t.build_prompt("", "a, b") == "Terms: a, b."


def test_build_prompt_is_bounded():
    assert len(t.build_prompt("x", ", ".join(["term"] * 500))) <= t._PROMPT_MAX_CHARS


def test_session_prompt_set_and_clear():
    t.set_session_prompt("s1", "Lecture: A.")
    assert t._session_prompts["s1"] == "Lecture: A."
    t.set_session_prompt("s1", "")
    assert "s1" not in t._session_prompts
