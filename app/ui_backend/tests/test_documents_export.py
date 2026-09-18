"""PDF and Word builders: structure, Markdown handling, transcript grouping."""

import zipfile
from datetime import datetime
from io import BytesIO

import documents_export as de


def _lecture(**overrides):
    base = dict(
        title="Test <Lecture> & co",
        recorded_at=datetime(2026, 9, 14, 21, 56),
        duration_seconds=6780,
        notes_version=3,
        notes_md="## Key Concepts\n- **Strategy**: a plan\n- with *italic* and `code`\n",
        transcript=[
            (0.5, "Hello."),
            (4.0, "Welcome."),
            (35.0, "Second paragraph."),
            (70.0, "Third."),
        ],
        qa=[("user", "How many?", None), ("assistant", "There is **one**.", "gemini/flash")],
    )
    base.update(overrides)
    return de.LectureDoc(**base)


def test_group_transcript_every_30_seconds():
    assert de.group_transcript(_lecture().transcript) == [
        (0.5, "Hello. Welcome."),
        (35.0, "Second paragraph."),
        (70.0, "Third."),
    ]


def test_sections_follow_content():
    assert _lecture().sections() == ["notes", "qa", "transcript"]
    assert _lecture(notes_md="", qa=[]).sections() == ["transcript"]


def test_subtitle():
    assert (
        _lecture().subtitle
        == "Recorded September 14, 2026, 09:56 PM · 1 h 53 min · Notes version 3"
    )
    assert _lecture(recorded_at=None, duration_seconds=600, notes_version=0).subtitle == "10 min"


def test_inline_runs():
    runs = de._inline_runs("a **b** c *d* `e`")
    assert runs == [
        ("a ", {}),
        ("b", {"bold": True}),
        (" c ", {}),
        ("d", {"italic": True}),
        (" ", {}),
        ("e", {"code": True}),
    ]


def test_pdf_builds_and_escapes():
    data = de.build_pdf(_lecture())
    assert data.startswith(b"%PDF-") and len(data) > 5_000


def test_docx_builds_with_all_sections():
    data = de.build_docx(_lecture())
    assert data[:2] == b"PK"
    with zipfile.ZipFile(BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode()
    for text in (
        "1. Notes",
        "2. Questions",
        "3. Full transcript",
        "Strategy",
        "How many?",
        "Second paragraph.",
    ):
        assert text in xml, text
