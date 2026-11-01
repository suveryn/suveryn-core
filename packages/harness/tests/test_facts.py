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
    retries: list[tuple[int, dict]] = []

    def answering(*answers):
        async def answer(req):
            asked.append(req.messages[-1].content)
            assert req.document_ids == [DOC] and req.case_id == CASE and req.max_tokens == 4096
            return response(answers[len(asked) - 1])
        return answer

    facts, got = asyncio.run(read_playbook(answering("Not a table.", TABLE), DEED_INTAKE, {DOC: "compromis.pdf"}, CASE, lambda n, shape: retries.append((n, shape))))
    assert [a.endswith(STRICTER) for a in asked] == [False, True] and [n for n, _ in retries] == [1]
    assert retries[0][1] == {"chars": 12, "lines": 1, "table_rows": 0, "named_rows": 0, "pipes_per_row": "0",
                             "finish": None, "reasoning_chars": 0}
    assert {f.id: f for f in facts}["price"].value == "EUR 412.500,00" and got.answer == TABLE

    asked.clear()
    with pytest.raises(Unreadable):
        asyncio.run(read_playbook(answering("Not a table.", "Still not."), DEED_INTAKE, {DOC: "compromis.pdf"}, CASE))
    assert len(asked) == 2  # never a third time


def test_an_unreadable_answers_shape_is_counts_only():
    """What the gateway logs when an answer isn't the table: never a word of it (VM check 2)."""
    from suveryn_harness.facts import answer_shape
    reshaped = "| # | fact | value | source |\n|---|---|---|---|\n| 1 | Verkopers | Jan Peeters [1] | [1] |\n| 2 | prijs | EUR 1 [2] | [2] |"
    shape = answer_shape(DEED_INTAKE, response(reshaped))
    assert shape["table_rows"] == 4 and shape["named_rows"] == 0 and shape["pipes_per_row"] == "5"
    assert not any("Peeters" in str(v) or "EUR" in str(v) for v in shape.values())
    assert answer_shape(DEED_INTAKE, response(TABLE))["named_rows"] == len(DEED_INTAKE.facts)


@pytest.mark.parametrize("missing", ["", "-", "\u2014", "niet gevonden"])
def test_a_deed_that_lacks_most_facts_is_read_with_them_not_found(missing):
    """VM check of 1a5cfea: on a thin deed the model left nine cells empty, and the parser took each
    empty row for the table's separator line, so too few rows were left and the run was unreadable."""
    found = {"sellers": "Jan Peeters [1]", "buyers": "Tom Janssens [1]", "property": "Kerkstraat 1, Gent [1]",
             "price": "EUR 412.500,00 [1]"}
    rows = "".join(f"| {f.id} | {found.get(f.id, missing)} | {'[1]' if f.id in found else ''} |\n" for f in DEED_INTAKE.facts)
    facts = read_facts(DEED_INTAKE, response("| id | value | source |\n|---|:---:|---|\n" + rows), {})
    assert facts is not None
    assert sorted(f.id for f in facts if f.found) == sorted(found)
    assert all(not f.value and not f.citations for f in facts if not f.found)


# ------------------------------------------------------------------ answers in words

def test_an_answer_in_words_is_mapped_only_to_the_facts_asked():
    from suveryn_harness.facts import map_prompt, read_mapping

    labels = {"epc": "Energieprestatiecertificaat", "soil": "Bodemattest", "deed_by": "Akte te verlijden tegen"}
    answer = "epc: 20260915-0002, label C\n- `deed_by`: 15 februari 2027\nprice: 1\nsoil: niet vermeld\nNONE"
    assert read_mapping(answer, labels) == {"epc": "20260915-0002, label C", "deed_by": "15 februari 2027"}
    assert read_mapping("NONE", labels) == {} and read_mapping("I can't tell.", labels) == {}
    prompt = map_prompt(labels, {"deed_by": "12 februari 2027"}, "EPC 20260915-0002 >>> label C")
    assert "- deed_by: Akte te verlijden tegen (now: 12 februari 2027)" in prompt and "> > > label C" in prompt


# ------------------------------------------------------------------ by meaning (Filip, 1 November 2026; VM regression 03c8f74)

def test_an_amount_or_a_date_is_compared_by_what_it_means():
    from suveryn_harness.facts import _by_meaning

    words = "Het voorschot bedraagt zesentwintigduizend achthonderd euro, te betalen bij ondertekening op twaalf mei tweeduizend veertien."
    assert _by_meaning("amount", "EUR 26.800,00", [words], ",") == (None, None)            # the same amount, in figures
    assert _by_meaning("amount", "EUR 28.600,00", [words], ",") == (None, "EUR 28.600,00")  # a different one: to check
    assert _by_meaning("date", "12/05/2014", [words], ",") == (None, None)
    assert _by_meaning("date", "uiterlijk vier maanden na de ondertekening", [words], ",") == ("not_a_date", None)
    assert _by_meaning("amount", "tien procent van de koopprijs", [words], ",") == ("not_an_amount", None)
    assert _by_meaning("amount", "412.500,00 EUR", ["De prijs bedraagt 412 500,00 EUR."], ",") == (None, None)  # a space between thousands


def test_the_check_reads_spaced_figures_and_dates_in_words():
    from suveryn_harness.calc import unverified_figures
    from suveryn_harness.support import _dates

    assert unverified_figures("De hypotheek bedraagt 1.250.000 EUR.", [], "een hypotheek van 1 250 000,00 EUR") == []
    assert (12, 5, 2014) in _dates("verleden op twaalf mei tweeduizend veertien")
    assert (12, 5, 2014) in _dates("le douze mai deux mille quatorze")


def test_not_known_yet_in_words_names_the_facts():
    """VM regression 03c8f74, finding 8: "Bodemattest: nog niet bekend." at the checkpoint placed nothing."""
    from suveryn_harness.facts import said_unknown

    labels = {"soil": "Bodemattest", "epc": "EPC-certificaat", "price": "Prijs"}
    assert said_unknown("Bodemattest: nog niet bekend.", labels) == ["soil"]
    assert said_unknown("Het EPC-certificaat en het bodemattest volgen later.", labels) == ["soil", "epc"]
    assert said_unknown("Attestation du sol : pas encore connue.", {"soil": "Attestation du sol"}) == ["soil"]
    assert said_unknown("Soil certificate: to follow", {"soil": "Soil certificate"}) == ["soil"]
    assert said_unknown("Bodemattest: BA-2026-114, geen verontreiniging.", labels) == []  # a value, not unknown
    assert said_unknown("Dat is nog niet bekend.", labels) == []                           # names no fact
