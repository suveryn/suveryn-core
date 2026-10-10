from suveryn_chat import cited_numbers, grounded_messages
from suveryn_engine import ChatMessage, Citation, SourceRef


def cit(text, page):
    return Citation(text=text, source=SourceRef(document_id="d1", page=page, location=f"p. {page} · Artikel {page}"))


def test_excerpts_first_question_last_history_kept():
    history = [ChatMessage(role="user", content="Eerdere vraag"), ChatMessage(role="assistant", content="Eerder antwoord")]
    msgs = grounded_messages(history, "Wat is de koopprijs?", [cit("De koopprijs bedraagt EUR 412.500,00.", 2)], ["akte.pdf"])
    assert [m.role for m in msgs] == ["system", "user", "assistant", "user"]
    last = msgs[-1].content
    assert last.startswith("EXCERPTS (the passages of the documents that best match the question, in reading order; "
                           "not the whole text):\n"
                           "[1] (akte.pdf, p. 2 · Artikel 2)\nDe koopprijs bedraagt EUR 412.500,00.")
    assert last.endswith("QUESTION: Wat is de koopprijs?")


def test_complete_documents_are_announced_as_such():
    last = grounded_messages([], "Waarover gaat deze akte?", [cit("Verkoop van een woning.", 1)], ["akte.pdf"], complete=True)[-1].content
    assert last.startswith("EXCERPTS (the complete text of the documents, in reading order):\n[1] (akte.pdf")


def test_no_passages_is_explicit():
    assert "(no matching passages were found)" in grounded_messages([], "Vraag?", [], [])[-1].content


def test_cited_numbers_in_order_of_first_use_and_in_range():
    assert cited_numbers("Prijs [2], waarborg [1][2], datum [7] en [3].", available=3) == [2, 1, 3]
    assert cited_numbers("Geen bronnen.", available=3) == []
