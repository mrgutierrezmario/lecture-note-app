"""Notes merging, de-duplication, the heuristic extractor and the focus prompt."""

from ai import notes_generator as ng


def test_merge_appends_new_sections_and_dedupes_bullets():
    existing = "## Key Concepts\n- **Strategy**: a plan\n"
    new = (
        "## Key Concepts\n- **Strategy**: a plan\n- **Tactics**: the steps\n\n"
        "## Definitions\n- **SWOT**: strengths, weaknesses…\n"
    )
    merged = ng.merge_notes(existing, new)
    assert merged.count("**Strategy**") == 1
    assert "**Tactics**" in merged
    assert "## Definitions" in merged and "**SWOT**" in merged


def test_merge_into_empty_is_identity():
    new = "## Examples\n- Apple's pricing\n"
    assert ng.merge_notes("", new).strip() == new.strip()


def test_heuristic_extractor_finds_deadlines():
    text = "Your book review is due October 5th. Remember the exam next week."
    md = ng.extract_heuristic_notes(text)
    assert "Action Items" in md or "Deadlines" in md
    assert "October 5th" in md or "due" in md.lower()


def test_focus_reaches_the_prompt():
    prompt = ng.EXTRACT_PROMPT_TEMPLATE.format(
        transcript="t", focus=ng.FOCUS_TEMPLATE.format(focus="formulas")
    )
    assert "focus on: formulas" in prompt
    plain = ng.EXTRACT_PROMPT_TEMPLATE.format(transcript="t", focus="")
    assert "focus on" not in plain
