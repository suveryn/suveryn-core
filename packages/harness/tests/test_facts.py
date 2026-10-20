"""Reading a playbook's facts from the model (suveryn_harness.facts, suveryn-tracker#51): deed intake's
table, each fact with its passages and the chat's checks; asked once more when it isn't the table."""

import asyncio

import pytest
from suveryn_harness import ChatResponse, Citation, SourceRef
from suveryn_harness.facts import STRICTER, Unreadable, read_facts, read_playbook
from suveryn_playbooks import DEED_INTAKE

DOC = "11111111-1111-1111-1111-111111111111"
CASE = "22222222-2222-2222-2222-222222222222"
TABLE = (
    "| id | value | source |\n|---|---|---|\n"
    "| sellers | Jan Peeters en Marie Claes [1] | [1] |\n"
    "| buyers | Tom Janssens [1] | [1] |\n"
    "| property | Woning, Kerkstraat 12, 9000 Gent [1] | [1] |\n"
    "| cadastral | | |\n"
    "| price | EUR 412.500,00 [1] | [1] |\n"
    "| deposit | EUR 41.250,00 aan de notaris [2] | [2] |\n"
    "| agreement_date | 3 oktober 2026 [1] | [1] |\n"
    "| deed_deadline | 15 januari 2027 [1] | [1] |\n"
    "| conditions | Financiering, 30 dagen [1] | [1] |\n"
    "| title | | |\n"
    "| epc | | |\n"
    "| soil | niet gevonden | |\n"
    "| occupancy | Vrij van gebruik [1] | [1] |\n"
)
PASSAGES = [
    Citation(text="Verkopers: Jan Peeters en Marie Claes. Koper: Tom Janssens. Woning, Kerkstraat 12, 9000 Gent. "
                  "De koopprijs bedraagt EUR 412.500,00. Getekend te Gent op 3 oktober 2026. De akte wordt verleden "
                  "uiterlijk op 15 januari 2027. Opschortende voorwaarde: financiering, 30 dagen. Vrij van gebruik.",
             source=SourceRef(document_id=DOC, page=1, location="p. 1")),
    Citation(text="Een voorschot van EUR 41.250,00 wordt betaald aan de notaris.", source=SourceRef(document_id=DOC, page=2, location="p. 2")),
]


def response(answer=TABLE, citations=PASSAGES) -> ChatResponse:
    """As ``ChatService.answer`` returns it: with the chat's own checks run on the answer."""
    from suveryn_harness.calc import unverified_figures
    from suveryn_harness.support import citation_issues
    source = "\n".join(c.text for c in citations)
    return ChatResponse(id="x", answer=answer, model="Qwen", citations=citations,
                        unverified_figures=unverified_figures(answer, [], source), citation_issues=citation_issues(answer, citations, []))


def test_read_facts_keeps_each_facts_passages_and_runs_the_check():
    facts = read_facts(DEED_INTAKE, response(), {DOC: "compromis.pdf"})
    assert facts is not None and [f.id for f in facts] == [f.id for f in DEED_INTAKE.facts]
    by = {f.id: f for f in facts}
    assert by["price"].value == "EUR 412.500,00" and by["price"].found and by["price"].issues == []
    assert [(c.n, c.page, c.filename) for c in by["price"].citations] == [(1, 1, "compromis.pdf")]
    assert by["deposit"].citations[0].n == 2 and "voorschot" in by["deposit"].citations[0].text
    assert not by["cadastral"].found and by["cadastral"].value == "" and by["cadastral"].citations == []
    assert not by["soil"].found  # "niet gevonden" is not a value
    assert by["occupancy"].value == "Vrij van gebruik"


def test_read_facts_flags_a_figure_the_passage_doesnt_contain():
    wrong = TABLE.replace("EUR 412.500,00 [1]", "EUR 415.500,00 [1]").replace("15 januari 2027 [1]", "15 januari 2028 [1]")
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(wrong), {DOC: "compromis.pdf"})}
    assert facts["price"].issues == ["415.500,00"]  # in no passage: the chat's unverified figure
    assert facts["deed_deadline"].issues and facts["agreement_date"].issues == []
    swapped = TABLE.replace("EUR 412.500,00 [1]", "EUR 41.250,00 [1]")  # in a passage, not the cited one
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(swapped), {DOC: "compromis.pdf"})}
    assert facts["price"].issues == ["41.250,00"] and facts["deposit"].issues == []
    assert facts["sellers"].issues == []  # other rows are untouched by a wrong figure elsewhere


def test_an_answer_that_isnt_the_table_is_unreadable():
    assert read_facts(DEED_INTAKE, response("De koopprijs is EUR 412.500,00 [1]."), {}) is None
    assert read_facts(DEED_INTAKE, response("| id | value | source |\n|---|---|---|\n| price | EUR 1 [1] | [1] |"), {}) is None


def test_a_fact_may_be_named_by_its_label_in_any_language_but_never_by_position():
    """Review 2026-10-17: a small model translates or paraphrases the id; a row is still never taken by position."""
    translated = (TABLE.replace("| sellers |", "| Verkoper(s) |").replace("| buyers |", "| **Acquéreur(s)** |")
                       .replace("| price |", "| Price |").replace("| agreement_date |", "| agreement date |"))
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(translated), {DOC: "compromis.pdf"})}
    assert facts["sellers"].value == "Jan Peeters en Marie Claes" and facts["buyers"].value == "Tom Janssens"
    assert facts["price"].value == "EUR 412.500,00" and facts["agreement_date"].value == "3 oktober 2026"
    shifted = TABLE.replace("| price | EUR 412.500,00 [1] | [1] |\n", "")  # a row left out: nothing moves up
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(shifted), {DOC: "compromis.pdf"})}
    assert not facts["price"].found and facts["deposit"].value.startswith("EUR 41.250,00")
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(TABLE.replace("| price |", "| something else |")), {})}
    assert not facts["price"].found  # an unknown name is dropped, not guessed


def test_read_playbook_asks_once_more_with_a_stricter_reminder_then_gives_up():
    asked: list[str] = []
    retries: list[int] = []

    def answering(*answers):
        async def answer(req):
            asked.append(req.messages[-1].content)
            assert req.document_ids == [DOC] and req.case_id == CASE and req.max_tokens == 4096
            return response(answers[len(asked) - 1])
        return answer

    facts, got = asyncio.run(read_playbook(answering("Not a table.", TABLE), DEED_INTAKE, {DOC: "compromis.pdf"}, CASE, retries.append))
    assert [a.endswith(STRICTER) for a in asked] == [False, True] and retries == [1]
    assert {f.id: f for f in facts}["price"].value == "EUR 412.500,00" and got.answer == TABLE

    asked.clear()
    with pytest.raises(Unreadable):
        asyncio.run(read_playbook(answering("Not a table.", "Still not."), DEED_INTAKE, {DOC: "compromis.pdf"}, CASE))
    assert len(asked) == 2  # never a third time
