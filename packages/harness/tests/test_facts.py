"""Reading a playbook's facts from the model (suveryn_harness.facts, suveryn-tracker#51): deed intake's
JSON, each fact with its passages and the chat's checks; lists and numbers (format 3); asked once more
when the answer isn't the object asked for."""

import asyncio
import json

import pytest
from suveryn_harness import ChatResponse, Citation, SourceRef
from suveryn_harness.facts import STRICTER, Unreadable, read_facts, read_playbook
from suveryn_playbooks import DEED_INTAKE, Wording, read_schema
from suveryn_playbooks.manifest import parse

DOC = "11111111-1111-1111-1111-111111111111"
CASE = "22222222-2222-2222-2222-222222222222"


def leaf(value, *sources):
    return {"value": value, "sources": list(sources)}


def party(name, *sources):
    return {"name": leaf(name, *sources), "address": leaf(None), "register": leaf(None)}


ANSWER = {
    "sellers": [party("Jan Peeters", 1), party("Marie Claes", 1)], "buyers": [party("Tom Janssens", 1)],
    "property": leaf("Woning, Kerkstraat 12, 9000 Gent", 1), "cadastral": leaf(None),
    "price": leaf("EUR 412.500,00", 1), "deposit": leaf("EUR 41.250,00 aan de notaris", 2),
    "agreement_date": leaf("3 oktober 2026", 1), "deed_deadline": leaf("15 januari 2027", 1),
    "conditions": [{"condition": leaf("Financiering", 1), "term": leaf("2 november 2026", 1)}], "title": leaf(None), "epc": leaf(""),
    "soil": leaf("niet gevonden"), "occupancy": leaf("Vrij van gebruik", 1),
}
LEAVES = [f.id for f in DEED_INTAKE.facts if f.kind != "list"]
PASSAGES = [
    Citation(text="Verkopers: Jan Peeters en Marie Claes. Koper: Tom Janssens. Woning, Kerkstraat 12, 9000 Gent. "
                  "De koopprijs bedraagt EUR 412.500,00. Getekend te Gent op 3 oktober 2026. De akte wordt verleden "
                  "uiterlijk op 15 januari 2027. Opschortende voorwaarde: financiering, tegen 2 november 2026. Vrij van gebruik.",
             source=SourceRef(document_id=DOC, page=1, location="p. 1")),
    Citation(text="Een voorschot van EUR 41.250,00 wordt betaald aan de notaris.", source=SourceRef(document_id=DOC, page=2, location="p. 2")),
]


def response(answer=None, citations=PASSAGES) -> ChatResponse:
    """As ``ChatService.answer`` returns it: with the chat's own checks run on the answer."""
    from suveryn_harness.calc import unverified_figures
    from suveryn_harness.support import citation_issues
    if answer is None:
        answer = ANSWER
    if not isinstance(answer, str):
        answer = json.dumps(answer, ensure_ascii=False)
    source = "\n".join(c.text for c in citations)
    return ChatResponse(id="x", answer=answer, model="Qwen", citations=citations,
                        unverified_figures=unverified_figures(answer, [], source), citation_issues=citation_issues(answer, citations, []))


def with_value(fact, value, *sources):
    return {**ANSWER, fact: leaf(value, *sources)}


def test_read_facts_keeps_each_facts_passages_and_runs_the_check():
    facts = read_facts(DEED_INTAKE, response(), {DOC: "compromis.pdf"})
    assert facts is not None and [f.id for f in facts] == [
        "sellers[1].name", "sellers[1].address", "sellers[1].register", "sellers[2].name", "sellers[2].address", "sellers[2].register",
        "buyers[1].name", "buyers[1].address", "buyers[1].register", "property", "cadastral", "price", "deposit", "agreement_date",
        "deed_deadline", "conditions[1].condition", "conditions[1].term", "title", "epc", "soil", "occupancy"]
    by = {f.id: f for f in facts}
    assert by["sellers[2].name"].value == "Marie Claes" and not by["sellers[2].register"].found
    assert by["conditions[1].term"].value == "2 november 2026" and by["conditions[1].term"].issues == []
    assert by["price"].value == "EUR 412.500,00" and by["price"].found and by["price"].issues == []
    assert [(c.n, c.page, c.filename) for c in by["price"].citations] == [(1, 1, "compromis.pdf")]
    assert by["deposit"].citations[0].n == 2 and "voorschot" in by["deposit"].citations[0].text
    assert not by["cadastral"].found and by["cadastral"].value == "" and by["cadastral"].citations == []
    assert not by["soil"].found and not by["epc"].found  # "niet gevonden" and "" are not values
    assert by["occupancy"].value == "Vrij van gebruik"


def test_read_facts_flags_a_figure_the_passage_doesnt_contain():
    wrong = with_value("price", "EUR 415.500,00", 1)
    wrong["deed_deadline"] = leaf("15 januari 2028", 1)
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(wrong), {DOC: "compromis.pdf"})}
    assert facts["price"].issues == ["415.500,00"]  # in no passage: the chat's unverified figure
    assert facts["deed_deadline"].issues and facts["agreement_date"].issues == []
    swapped = with_value("price", "EUR 41.250,00", 1)  # in a passage, not the cited one
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(swapped), {DOC: "compromis.pdf"})}
    assert facts["price"].issues == ["41.250,00"] and facts["deposit"].issues == []
    assert facts["sellers[1].name"].issues == []  # other values are untouched by a wrong figure elsewhere


def test_sources_the_model_names_wrongly_are_dropped_and_markers_in_the_value_count():
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(with_value("price", "EUR 412.500,00 [1]", 7)), {DOC: "a.pdf"})}
    assert [c.n for c in facts["price"].citations] == [1] and facts["price"].value == "EUR 412.500,00"
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response({**ANSWER, "price": "EUR 412.500,00"}), {})}  # a bare value: tolerated, uncited
    assert facts["price"].value == "EUR 412.500,00" and facts["price"].citations == []


def test_an_answer_that_isnt_the_object_is_unreadable_but_a_fenced_or_wrapped_one_reads():
    assert read_facts(DEED_INTAKE, response("De koopprijs is EUR 412.500,00 [1]."), {}) is None
    assert read_facts(DEED_INTAKE, response('{"prijs": {"value": "EUR 1", "sources": [1]}}'), {}) is None  # not the keys asked for
    assert read_facts(DEED_INTAKE, response("| id | value | source |\n|---|---|---|\n| price | EUR 1 [1] | [1] |"), {}) is None
    fenced = "```json\n" + json.dumps(ANSWER) + "\n```"
    assert {f.id: f for f in read_facts(DEED_INTAKE, response(fenced), {})}["price"].value == "EUR 412.500,00"
    wrapped = "Here is the table:\n" + json.dumps(ANSWER) + "\nDone."
    assert {f.id: f for f in read_facts(DEED_INTAKE, response(wrapped), {})}["price"].value == "EUR 412.500,00"


def test_read_playbook_asks_with_the_schema_and_once_more_with_a_stricter_reminder_then_gives_up():
    asked: list[str] = []
    retries: list[tuple[int, dict]] = []

    def answering(*answers):
        async def answer(req):
            asked.append(req.messages[-1].content)
            assert req.document_ids == [DOC] and req.case_id == CASE and req.max_tokens == 6144
            assert req.json_schema == read_schema(DEED_INTAKE.facts) and req.json_schema["required"][0] == "sellers"
            return response(answers[len(asked) - 1])
        return answer

    facts, got = asyncio.run(read_playbook(answering("Not JSON.", ANSWER), DEED_INTAKE, {DOC: "compromis.pdf"}, CASE, lambda n, shape: retries.append((n, shape))))
    assert [a.endswith(STRICTER) for a in asked] == [False, True] and [n for n, _ in retries] == [1]
    assert retries[0][1] == {"chars": 9, "lines": 1, "json": False, "keys": 0, "named_keys": 0, "finish": None, "reasoning_chars": 0}
    assert {f.id: f for f in facts}["price"].value == "EUR 412.500,00" and json.loads(got.answer) == ANSWER

    asked.clear()
    with pytest.raises(Unreadable):
        asyncio.run(read_playbook(answering("Not JSON.", "Still not."), DEED_INTAKE, {DOC: "compromis.pdf"}, CASE))
    assert len(asked) == 2  # never a third time


def test_a_read_step_over_some_facts_asks_for_those_only():
    async def answer(req):
        assert set(req.json_schema["properties"]) == {"price", "deposit"} and "only these facts" in req.messages[-1].content
        return response({"price": leaf("EUR 412.500,00", 1), "deposit": leaf(None)})
    facts, _ = asyncio.run(read_playbook(answer, DEED_INTAKE, {DOC: "a.pdf"}, CASE, fact_ids={"price", "deposit"}))
    assert [(f.id, f.found) for f in facts] == [("price", True), ("deposit", False)]


def test_an_unreadable_answers_shape_is_counts_only():
    """What the gateway logs when an answer isn't the object: never a word of it (VM check 2)."""
    from suveryn_harness.facts import answer_shape
    reshaped = '{"facts": [{"id": "Verkopers", "value": "Jan Peeters", "sources": [1]}, {"id": "prijs", "value": "EUR 1"}]}'
    shape = answer_shape(DEED_INTAKE, response(reshaped))
    assert shape["json"] and shape["keys"] == 1 and shape["named_keys"] == 0
    assert not any("Peeters" in str(v) or "EUR" in str(v) for v in shape.values())
    assert answer_shape(DEED_INTAKE, response())["named_keys"] == len(DEED_INTAKE.facts)  # a list is one key


@pytest.mark.parametrize("missing", [None, "", "-", "—", "niet gevonden"])
def test_a_deed_that_lacks_most_facts_is_read_with_them_not_found(missing):
    """A thin deed: most values null or "not found" in words; every one is read as not found, never as a value."""
    found = {"property": "Kerkstraat 1, Gent", "price": "EUR 412.500,00"}
    answer = {f.id: ([] if f.kind == "list" else leaf(found[f.id], 1) if f.id in found else leaf(missing)) for f in DEED_INTAKE.facts}
    answer["sellers"] = [party("Jan Peeters", 1)]
    facts = read_facts(DEED_INTAKE, response(answer), {})
    assert facts is not None
    assert sorted(f.id for f in facts if f.found) == sorted([*found, "sellers[1].name"])
    assert all(not f.value and not f.citations for f in facts if not f.found)
    assert {f.id for f in facts if f.id in ("buyers", "conditions")} == {"buyers", "conditions"}  # the empty lists: one not-found fact each


# ------------------------------------------------------------------ lists and numbers (format 3)

FORMATION = """
manifest: 3
id: playbook/be-notary/formation-test
pack: pack/be-notary
version: "1.0"
name: Formation test
case_types: [company-formation]
facts:
  - id: company_name
    ask: the name of the company
  - id: contribution
    ask: the total contribution in money
    kind: amount
  - id: shares
    ask: the number of shares issued
    kind: number
  - id: founders
    ask: the founders, one entry per founder
    kind: list
    of:
      - id: name
        ask: the founder's full name
      - id: shares
        ask: the number of shares this founder takes
        kind: number
      - id: contribution
        ask: this founder's contribution in money
        kind: amount
  - id: conditions
    ask: the conditions attached, one entry each
    kind: list
    of: text
instructions: Read the excerpts.
steps:
  - id: read
    kind: read
    facts: all
  - id: confirm
    kind: checkpoint
    by: anyone_in_case
"""
WORDS = {lang: Wording("Formation", "Reads it", {"company_name": "Name", "contribution": "Contribution", "shares": "Shares",
                                                 "founders": "Founder(s)", "founders.name": "Name", "founders.shares": "Shares",
                                                 "founders.contribution": "Contribution", "conditions": "Conditions"})
         for lang in ("en", "nl", "fr")}
FORMATION_PASSAGES = [
    Citation(text="Suveryn Labs BV. Inbreng in geld: 50.000 euro, verdeeld in 1000 aandelen. Oprichters: Filip Tack, 600 aandelen, "
                  "30.000 euro; Anna Peeters, 400 aandelen, 20.000 euro.", source=SourceRef(document_id=DOC, page=1, location="p. 1")),
    Citation(text="Voorwaarde: de bankverklaring wordt voorgelegd bij het verlijden.", source=SourceRef(document_id=DOC, page=3, location="p. 3")),
]


@pytest.fixture
def formation():
    return parse(FORMATION, where="formation.yaml").to_playbook(WORDS)


def test_a_lists_entries_become_facts_by_path_in_the_documents_order(formation):
    answer = {"company_name": leaf("Suveryn Labs BV", 1), "contribution": leaf("50.000 euro", 1), "shares": leaf("1000 aandelen", 1),
              "founders": [{"name": leaf("Filip Tack", 1), "shares": leaf("600 aandelen", 1), "contribution": leaf("30.000 euro", 1)},
                           {"name": leaf("Anna Peeters", 1), "shares": leaf("400", 1), "contribution": leaf(None)}],
              "conditions": [leaf("de bankverklaring wordt voorgelegd bij het verlijden", 2)]}
    facts = read_facts(formation, response(answer, FORMATION_PASSAGES), {DOC: "ontwerp.pdf"})
    assert [f.id for f in facts] == ["company_name", "contribution", "shares", "founders[1].name", "founders[1].shares",
                                     "founders[1].contribution", "founders[2].name", "founders[2].shares", "founders[2].contribution",
                                     "conditions[1]"]
    by = {f.id: f for f in facts}
    assert by["founders[2].name"].value == "Anna Peeters" and by["founders[2].name"].citations[0].page == 1
    assert not by["founders[2].contribution"].found
    assert by["conditions[1]"].citations[0].n == 2 and by["conditions[1]"].issues == []
    assert all(f.issues == [] and f.needs is None for f in facts if f.found)


def test_a_number_is_checked_by_meaning_against_its_passage(formation):
    answer = {"company_name": leaf(None), "contribution": leaf(None), "shares": leaf("1.000", 1),
              "founders": [{"name": leaf("Filip Tack", 1), "shares": leaf("650 aandelen", 1), "contribution": leaf("dertigduizend euro", 1)},
                           {"name": leaf("Anna Peeters", 1), "shares": leaf("de rest", 1), "contribution": leaf("20.000 euro", 1)}],
              "conditions": []}
    by = {f.id: f for f in read_facts(formation, response(answer, FORMATION_PASSAGES), {})}
    assert by["shares"].issues == []                                   # "1.000" is "1000" in the passage, read in its decimal style
    assert by["founders[1].shares"].issues == ["650 aandelen"]        # 650 is in no passage
    assert by["founders[1].contribution"].issues == []                # thirty thousand in words agrees with 30.000
    assert by["founders[2].shares"].needs == "not_a_number"           # no number at all: a person works it out
    assert by["conditions"].found is False and by["conditions"].id == "conditions"  # an empty list: the list itself, not found


def test_a_list_the_documents_name_nothing_of_is_one_not_found_fact_and_too_many_entries_are_cut(formation):
    from suveryn_playbooks.paths import MAX_ENTRIES
    answer = {"company_name": leaf("X", 1), "contribution": leaf(None), "shares": leaf(None), "founders": [], "conditions": "not a list"}
    by = {f.id: f for f in read_facts(formation, response(answer, FORMATION_PASSAGES), {})}
    assert not by["founders"].found and not by["conditions"].found
    many = {**answer, "conditions": [leaf(f"voorwaarde {i}", 2) for i in range(MAX_ENTRIES + 5)]}
    facts = read_facts(formation, response(many, FORMATION_PASSAGES), {})
    assert sum(1 for f in facts if f.id.startswith("conditions[")) == MAX_ENTRIES
    broken = {**answer, "founders": ["Filip Tack", {"name": leaf("Anna Peeters", 1)}]}  # entries that aren't records: their fields not found
    by = {f.id: f for f in read_facts(formation, response(broken, FORMATION_PASSAGES), {})}
    assert not by["founders[1].name"].found and by["founders[2].name"].value == "Anna Peeters" and not by["founders[2].shares"].found


def test_the_schema_the_server_enforces_has_the_facts_shape(formation):
    s = read_schema(formation.facts)
    assert list(s["properties"]) == ["company_name", "contribution", "shares", "founders", "conditions"] and s["additionalProperties"] is False
    founders = s["properties"]["founders"]
    assert founders["type"] == "array" and list(founders["items"]["properties"]) == ["name", "shares", "contribution"]
    assert s["properties"]["conditions"]["items"] == s["properties"]["company_name"]
    assert s["properties"]["company_name"]["properties"]["value"]["type"] == ["string", "null"]
    assert "founders" in formation.instructions and '"conditions": [' in formation.instructions


# ------------------------------------------------------------------ answers in words

def test_an_answer_in_words_is_mapped_only_to_the_facts_asked():
    from suveryn_harness.facts import map_prompt, read_mapping

    labels = {"epc": "Energieprestatiecertificaat", "soil": "Bodemattest", "deed_by": "Akte te verlijden tegen"}
    answer = "epc: 20260915-0002, label C\n- `deed_by`: 15 februari 2027\nprice: 1\nsoil: niet vermeld\nNONE"
    assert read_mapping(answer, labels) == {"epc": "20260915-0002, label C", "deed_by": "15 februari 2027"}
    assert read_mapping("NONE", labels) == {} and read_mapping("I can't tell.", labels) == {}
    prompt = map_prompt(labels, {"deed_by": "12 februari 2027"}, "EPC 20260915-0002 >>> label C")
    assert "- deed_by: Akte te verlijden tegen (now: 12 februari 2027)" in prompt and "> > > label C" in prompt


def test_a_choice_answered_in_words_is_mapped_to_its_option():
    """The GPU round's playbook runs (5 November 2026): "kosteloos" and "geen aparte vertrouwenspersoon" couldn't be
    placed on the care mandate's pay and trusted person: the prompt gave the label only, and the option ``none`` read
    as "nothing"."""
    from suveryn_harness.facts import map_prompt, read_mapping

    labels = {"remuneration": "Vergoeding lasthebbers", "trusted_person": "Vertrouwenspersoon", "reporting": "Verslag"}
    choices = {"remuneration": {"unpaid": "Kosteloos", "paid": "Bezoldigd"}, "trusted_person": {"none": "Geen", "named": "Aangeduid"}}
    prompt = map_prompt(labels, {}, "Kosteloos, geen aparte vertrouwenspersoon.", choices)
    assert "- remuneration: Vergoeding lasthebbers (a choice; options: unpaid = Kosteloos; paid = Bezoldigd)" in prompt
    assert "- reporting: Verslag\n" in prompt + "\n" and "the id of the option" in prompt
    assert read_mapping("remuneration: unpaid\ntrusted_person: none", labels, choices) == {"remuneration": "unpaid", "trusted_person": "none"}
    assert read_mapping("reporting: none", labels, choices) == {}  # not a choice: "none" is still nothing
    assert read_mapping("NOTHING", labels, choices) == {} and "the single word NOTHING" in prompt and "`trusted_person: none`" in prompt


# ------------------------------------------------------------------ by meaning (decision, 1 November 2026; VM regression 03c8f74)

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


def test_a_choice_is_read_as_one_of_its_options_or_not_at_all():
    from suveryn_harness.facts import option_of
    manifest = FORMATION.replace("  - id: conditions\n", "  - id: contribution_kind\n    ask: how the contribution is made\n    kind: choice\n    options: [cash, in_kind, mixed]\n  - id: conditions\n")
    p = parse(manifest, where="formation.yaml").to_playbook({l: Wording("F", "f", {**WORDS["en"].labels, "contribution_kind": "Contribution"}) for l in ("en", "nl", "fr")})
    base = {"company_name": leaf(None), "contribution": leaf(None), "shares": leaf(None), "founders": [], "conditions": []}
    for given, expected in (("in_kind", "in_kind"), ("In kind", "in_kind"), ("cash", "cash"), ("gold bars", None), (None, None)):
        by = {f.id: f for f in read_facts(p, response({**base, "contribution_kind": leaf(given, 1)}, FORMATION_PASSAGES), {})}
        assert (by["contribution_kind"].value or None) == expected and by["contribution_kind"].found == (expected is not None), given
    assert read_schema(p.facts)["properties"]["contribution_kind"]["properties"]["value"] == {"enum": ["cash", "in_kind", "mixed", None]}
    assert "one of cash, in_kind, mixed, or null" in p.instructions
    labels = {"cash": "In geld", "in_kind": "In natura", "mixed": "Gemengd"}
    assert option_of("in natura", ("cash", "in_kind", "mixed"), labels) == "in_kind" and option_of("cash", ("cash",), labels) == "cash"
    assert option_of("goud", ("cash", "in_kind"), labels) is None


TERM = Citation(text="De authentieke akte wordt verleden uiterlijk binnen vier maanden na de ondertekening van deze overeenkomst. "
                     "Opschortende voorwaarde: financiering, binnen zes weken na de ondertekening.",
                source=SourceRef(document_id=DOC, page=4, location="p. 4"))


def test_a_term_is_worked_out_from_the_date_it_counts_from_and_says_how():
    """Board P01, deed intake 1.4: "binnen vier maanden na de ondertekening" counted from the agreement's date
    (12 October 2026) is 12 February 2027, worked out and to check; the term as written is kept with how."""
    answer = {**ANSWER, "agreement_date": leaf("12 oktober 2026", 1),
              "deed_deadline": leaf("uiterlijk binnen vier maanden na de ondertekening van deze overeenkomst", 3),
              "conditions": [{"condition": leaf("Financiering", 3), "term": leaf("binnen zes weken na de ondertekening", 3)}]}
    passages = [PASSAGES[0].model_copy(update={"text": PASSAGES[0].text.replace("3 oktober 2026", "12 oktober 2026")}), PASSAGES[1], TERM]
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(answer, passages), {DOC: "compromis.pdf"})}
    deadline = facts["deed_deadline"]
    assert (deadline.value, deadline.needs) == ("12 februari 2027", "computed")
    assert deadline.computed == {"written": "uiterlijk binnen vier maanden na de ondertekening van deze overeenkomst", "from": "agreement_date",
                                 "base": "2026-10-12", "amount": 4, "unit": "month", "direction": "after", "date": "2027-02-12"}
    assert deadline.citations[0].page == 4  # the passage with the term stays its source
    term = facts["conditions[1].term"]
    assert (term.value, term.needs, term.computed["unit"]) == ("23 november 2026", "computed", "week")
    assert facts["agreement_date"].needs is None and facts["agreement_date"].computed is None


def test_a_term_without_a_date_to_count_from_or_in_working_days_stays_as_written():
    passages = [*PASSAGES, TERM]
    no_base = {**ANSWER, "agreement_date": leaf(None), "deed_deadline": leaf("binnen vier maanden na de ondertekening", 3)}
    deadline = {f.id: f for f in read_facts(DEED_INTAKE, response(no_base, passages), {})}["deed_deadline"]
    assert (deadline.value, deadline.needs, deadline.computed) == ("binnen vier maanden na de ondertekening", "not_a_date", None)
    working = {**ANSWER, "deed_deadline": leaf("binnen vijftien werkdagen na de ondertekening", 3)}
    assert {f.id: f for f in read_facts(DEED_INTAKE, response(working, passages), {})}["deed_deadline"].needs == "not_a_date"


@pytest.mark.parametrize("written, base, expect", [
    ("binnen vier maanden na de ondertekening", (31, 10, 2026), "28 februari 2027"),        # no 31 February: the month's last day
    ("dans les deux mois de la signature", (12, 10, 2026), "12 décembre 2026"),
    ("quatre-vingt-dix jours à compter de la signature", (12, 10, 2026), "10 janvier 2027"),
    ("within 30 days after signing", (12, 10, 2026), "11 November 2026"),
    ("two weeks before the deed", (12, 10, 2026), "28 September 2026"),
    ("binnen een jaar na de ondertekening", (29, 2, 2028), "28 februari 2029"),
    ("drie (3) maanden na de ondertekening", (12, 10, 2026), "12 januari 2027"),
])
def test_terms_in_three_languages(written, base, expect):
    from suveryn_harness.terms import work_out
    assert work_out(written, base)[0] == expect


@pytest.mark.parametrize("written", ["binnen vier maanden", "binnen 15 werkdagen na de ondertekening", "12 februari 2027",
                                     "vier maanden of zes weken na de ondertekening", "tien procent van de prijs"])
def test_what_isnt_one_certain_term_is_not_worked_out(written):
    from suveryn_harness.terms import work_out
    assert work_out(written, (12, 10, 2026)) is None


def test_a_facts_passage_keeps_the_text_around_it_for_the_source_panel():
    """Board P02: a playbook's source opens the conversation's source panel, the passage in its context."""
    from suveryn_harness.schemas import PassageContext
    text = PASSAGES[1].text
    around = PASSAGES[1].model_copy(update={"context": PassageContext(text=f"Artikel 3. {text} Ontvangstbewijs volgt.", start=11, end=11 + len(text))})
    facts = {f.id: f for f in read_facts(DEED_INTAKE, response(citations=[PASSAGES[0], around]), {DOC: "compromis.pdf"})}
    ctx = facts["deposit"].citations[0].context
    assert ctx is not None and ctx.text[ctx.start:ctx.end] == text
    assert facts["price"].citations[0].context is None
