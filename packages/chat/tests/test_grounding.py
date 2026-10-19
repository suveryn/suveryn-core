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


def test_earlier_answers_keep_their_citations_as_neutral_markers():
    """Their numbers point at earlier excerpts, so they become [*]; stripped, the model took the uncited
    answers for the style to follow and from the second question on cited nothing."""
    history = [ChatMessage(role="user", content="Wat is de prijs [1]?"),
               ChatMessage(role="assistant", content="De koopprijs is EUR 412.500,00 [1][2].")]
    msgs = grounded_messages(history, "En de waarborg?", [cit("Waarborg EUR 41.250,00.", 3)], ["akte.pdf"])
    assert msgs[2].content == "De koopprijs is EUR 412.500,00 [*][*]."
    assert msgs[1].content == "Wat is de prijs [1]?"  # a question is the user's own text


def test_the_last_words_before_the_question_ask_for_citations():
    last = grounded_messages([], "Wat is de koopprijs?", [cit("De koopprijs bedraagt EUR 412.500,00.", 2)], ["akte.pdf"])[-1].content
    before_question = last.rsplit("QUESTION:", 1)[0]
    assert "Cite the excerpts above as [1], [2] after every statement in this answer too" in before_question.splitlines()[-2]


def test_complete_documents_are_announced_as_such():
    last = grounded_messages([], "Waarover gaat deze akte?", [cit("Verkoop van een woning.", 1)], ["akte.pdf"], complete=True)[-1].content
    assert last.startswith("EXCERPTS (the complete text of the documents, in reading order):\n[1] (akte.pdf")


def test_no_passages_is_explicit():
    assert "(no matching passages were found)" in grounded_messages([], "Vraag?", [], [])[-1].content


def test_cited_numbers_in_order_of_first_use_and_in_range():
    assert cited_numbers("Prijs [2], waarborg [1][2], datum [7] en [3].", available=3) == [2, 1, 3]
    assert cited_numbers("Geen bronnen.", available=3) == []
