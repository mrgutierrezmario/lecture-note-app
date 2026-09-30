"""Whisper's filler over silence ("Thank you.", "Thank you for watching.") and
echoes of the lecture prompt are dropped; real lecture speech is kept.
Examples are from a 90-minute lecture on 2026-09-28."""

import pytest

from ai import transcriber as t

FILLER = [
    "Thank you.",
    "Thank you very much.",
    "Thank you for watching.",
    "Thank you for watching!",
    "Thank you very much for your time.",
    "Thank you so much.",
    "Thanks for watching.",
    "Please subscribe to my channel.",
    "Bye.",
    "You",
]

REAL = [
    "So yeah, I think those things have really helped.",
    "Thank you for that question, it's a good one about Porter's forces.",
    "Could give you some insights, try to meet them for 20 minutes.",
    "And lunch is the third best, but...",
    "I got it.",
    "This is a video I want you to watch before next week about negotiation.",
]


@pytest.fixture()
def session():
    t.set_session_prompt("s1", "", "MGT699-09-28-26")
    yield "s1"
    t.set_session_prompt("s1", "")


@pytest.mark.parametrize("text", FILLER)
def test_filler_is_dropped(text, session):
    assert t._is_hallucination(t._normalize(text), session)


@pytest.mark.parametrize("text", REAL)
def test_lecture_speech_is_kept(text, session):
    assert not t._is_hallucination(t._normalize(text), session)


def test_prompt_echo_is_dropped(session):
    assert t._is_hallucination(t._normalize("This is a video of MGT699-29."), session)


def test_prompt_echo_needs_a_prompt():
    # Without a lecture prompt there is nothing to echo, so the line is kept.
    assert not t._is_hallucination(t._normalize("This is a video of the market."), None)


# Lines from the BIA568-09-30-26 lecture, where the title was in Whisper's prompt.
TITLE_ECHOES = ["BIA568-09-30-26.", "BIA568-09-30.", "BIA568-29-30.", "BIA568-30-26.", "BIA568"]
TITLE_REAL = [
    "BIA568 is a hybrid model in which AI handles routine queries.",
    "25%. So initially, they were very optimistic and",
    "30, 26.",
]


@pytest.fixture()
def bia_session():
    t.set_session_prompt("s2", "", "BIA568-09-30-26")
    yield "s2"
    t.set_session_prompt("s2", "")


@pytest.mark.parametrize("text", TITLE_ECHOES)
def test_title_echo_is_dropped(text, bia_session):
    assert t._is_hallucination(t._normalize(text), bia_session)


@pytest.mark.parametrize("text", TITLE_REAL)
def test_speech_near_title_is_kept(text, bia_session):
    assert not t._is_hallucination(t._normalize(text), bia_session)


def test_title_is_not_sent_to_whisper():
    assert "BIA568" not in t.build_prompt(None)
