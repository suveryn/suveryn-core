"""sūveryn's export mark found in an upload's text (docs/design/chat-ui.md §6)."""
import pytest

pytest.importorskip("suveryn_rag")
from suveryn_rag.marks import find_mark  # noqa: E402


def test_the_mark_is_found_in_any_language_and_its_line_kept():
    page = "Article 2. The price.\nMade by sūveryn: answer from case 2026/0611, 19/10/2026 · sūveryn-ref A-3F9C2E1B\n"
    assert find_mark(["", page]) == {"ref": "A-3f9c2e1b", "kind": "answer",
                                     "line": "Made by sūveryn: answer from case 2026/0611, 19/10/2026 · sūveryn-ref A-3F9C2E1B"}
    # French words, and ū split into u and a combining macron as some PDFs store it
    fr = "Créé par su\\u0304veryn : playbook · su\\u0304veryn-ref P-0a1b2c3d".encode().decode("unicode_escape")
    assert find_mark([fr])["ref"] == "P-0a1b2c3d" and find_mark([fr])["kind"] == "playbook"


def test_no_mark_and_near_misses_are_nothing():
    assert find_mark(["An ordinary deed without a mark."]) is None
    assert find_mark(["sūveryn-ref A-123"]) is None          # too short to be a reference
    assert find_mark(["sūveryn-ref X-3f9c2e1b"]) is None     # no such kind
    assert find_mark([]) is None


def test_a_word_answer_saved_as_pdf_still_carries_the_mark():
    """fixtures/marked-answer.pdf: an answer exported to Word by the chat UI (lib/office.ts) and saved
    as PDF with LibreOffice; the mark is the footer line, read from the PDF's text layer."""
    from pathlib import Path

    pytest.importorskip("pypdfium2")
    from suveryn_rag.extract import text_layer

    found = find_mark(text_layer(Path(__file__).parent / "fixtures" / "marked-answer.pdf"))
    assert found and found["ref"] == "A-e063906e" and found["kind"] == "answer" and "case 2026/0611" in found["line"]
