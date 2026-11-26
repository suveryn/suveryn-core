"""Playbook runs (suveryn-tracker#51): deed intake as a routine (docs/design/playbooks.md, "The
routine"): the playbook asks for the agreement, reads the case's documents, asks about what it
couldn't find, waits at the checkpoint for a person, stores the summary as a document with origin
``playbook``; and it can be paused, stopped and cancelled. Reading the model's table is the
harness's and tested there (packages/harness/tests/test_facts.py); the order of steps without a
database is test_playbook_runtime.py."""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.cases import CaseSettings
from suveryn_api_gateway.playbooks import RunStore, summary_text
from suveryn_harness import LlamaServerClient, LLMSettings
from suveryn_harness.facts import read_facts
from suveryn_playbooks import DEED_INTAKE
from suveryn_rag.store import Scope
from test_auth import SETTINGS, FakeKeycloak
from test_cases import ALICE, BOB, NEW, FakeCases, FakeDirectory, admin_headers
from test_conversations import FakeConversations, as_user
from test_documents import DOC, FakeDocuments, llm_transport

# The model's answer for deed intake (the facts' JSON) and its passages: the harness's own test fixtures (reading it is the harness's).
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "harness" / "tests"))
from model_server import garbled as model_garbled
from model_server import streamed
from test_facts import ANSWER, response
from test_facts import DOC as TABLE_DOC

TABLE = json.dumps(ANSWER, ensure_ascii=False)


def test_summary_text_uses_the_confirmed_values_and_the_language():
    from suveryn_api_gateway.playbooks import Run, playbook_out
    facts = read_facts(DEED_INTAKE, response(), {TABLE_DOC: "compromis.pdf"})
    for f in facts:
        f.confirmed = "EUR 412.000,00" if f.id == "price" else f.value
    run = Run(id=str(uuid.uuid4()), case_id=str(uuid.uuid4()), playbook_id=DEED_INTAKE.id, playbook_version="1.0",
              status="done", documents=[DOC], started_by=ALICE, started_at="2026-10-17T10:00:00Z", facts=facts,
              playbook=playbook_out(DEED_INTAKE))
    # the title and labels are the playbook's own words in that language (suveryn_playbooks, docs/translations.md)
    text = summary_text(DEED_INTAKE, "2026/0417", run, "fr")
    assert text.startswith("Analyse de l'acte 2026/0417\n\nplaybook/be-notary/deed-intake 1.0")
    assert "Prix: EUR 412.000,00 (compromis.pdf p. 1)" in text and "Données cadastrales: —" in text
    assert summary_text(DEED_INTAKE, "2026/0417", run, "de").startswith("Deed intake 2026/0417")  # unknown: English
    # provenance (review 2026-10-17): the run's version, not the playbook's as installed now
    older = run.model_copy(update={"playbook_version": "0.9"})
    assert "playbook/be-notary/deed-intake 0.9" in summary_text(DEED_INTAKE, "2026/0417", older, "en")


# ------------------------------------------------------------------ through the app (needs PostgreSQL for the runs)

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")


@pytest.fixture
def runs():
    s = RunStore(URL)
    yield s
    s._execute("DELETE FROM conversations WHERE run_id IN (SELECT id FROM playbook_runs WHERE started_by IN (%s, %s, %s, %s))", (ALICE, BOB, "notaris.test", "bob.test"))
    s._execute("DELETE FROM case_facts WHERE run_id IN (SELECT id FROM playbook_runs WHERE started_by IN (%s, %s, %s, %s))", (ALICE, BOB, "notaris.test", "bob.test"))
    s._execute("DELETE FROM playbook_runs WHERE started_by IN (%s, %s, %s, %s)", (ALICE, BOB, "notaris.test", "bob.test"))
    s._execute("DELETE FROM playbook_settings", ())
    s.close()


@pytest.fixture
def office(runs):
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    captured = []
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport(captured, text=TABLE))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases, runs=runs,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        yield c, kc, cases, docs, captured


@needs_db
def test_a_term_worked_out_from_the_agreements_date_is_kept_with_how(runs):
    """Board P01, deed intake 1.4: a deadline written as a term is stored as the date worked out, with how, and stays to check."""
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    answer = {**ANSWER, "deed_deadline": {"value": "binnen vier maanden na de ondertekening", "sources": [1]}}
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text=json.dumps(answer, ensure_ascii=False)))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases, runs=runs,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        cid, alice, _ = a_case_with_a_contributor(c, kc)
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice).json()["id"]
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        deliver(c, RUN.format(cid=cid, rid=rid), alice, text="Het compromis.")
        run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
        deadline = {f["id"]: f for f in run["facts"]}["deed_deadline"]
        assert (deadline["value"], deadline["needs"]) == ("3 februari 2027", "computed")
        assert deadline["computed"]["written"] == "binnen vier maanden na de ondertekening" and deadline["computed"]["from"] == "agreement_date"
        assert (deadline["computed"]["base"], deadline["computed"]["date"]) == ("2026-10-03", "2027-02-03")


@needs_db
def test_a_read_of_documents_longer_than_one_reading_says_so(office):
    """Documents longer than one reading takes are read by their best-matching passages, not every page: the read
    step keeps their names, the thread says so before the ask, and the summary ends with it."""
    c, kc, cases, docs, _ = office
    docs.whole = False
    cid, alice, _ = a_case_with_a_contributor(c, kc)
    rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice).json()["id"]
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    deliver(c, RUN.format(cid=cid, rid=rid), alice, text="Het compromis.")
    run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
    in_part = run["steps"]["agreement_read"]["in_part"]
    assert len(in_part) == 1 and in_part[0]  # the document's name, as the run read it
    said = [t for t in run["turns"] if t["meta"].get("kind") == "read_in_part"]
    assert len(said) == 1 and said[0]["meta"]["step"] == "agreement_read" and said[0]["meta"]["documents"] == run["steps"]["agreement_read"]["in_part"]
    kinds = [t["meta"].get("kind") for t in run["turns"] if t["role"] == "playbook"]
    assert kinds.index("read_in_part") < len(kinds) - 1  # said before what the run now waits on


def test_the_summary_ends_with_the_documents_read_in_part():
    from suveryn_api_gateway.playbooks import Run, StepState, playbook_out
    facts = read_facts(DEED_INTAKE, response(), {TABLE_DOC: "compromis.pdf"})
    run = Run(id=str(uuid.uuid4()), case_id=str(uuid.uuid4()), playbook_id=DEED_INTAKE.id, playbook_version="1.4",
              status="done", documents=[DOC], started_by=ALICE, started_at="2026-10-17T10:00:00Z", facts=facts, playbook=playbook_out(DEED_INTAKE),
              steps={"title_read": StepState(status="done", in_part=["eigendomstitel.pdf"])})
    assert summary_text(DEED_INTAKE, "2026/0417", run, "nl").endswith("Gedeeltelijk gelezen, niet elke pagina: eigendomstitel.pdf")
    whole = run.model_copy(update={"steps": {"title_read": StepState(status="done")}})
    assert "Gedeeltelijk" not in summary_text(DEED_INTAKE, "2026/0417", whole, "nl")


def deliver(c, url, headers, **body):
    """Deed intake's three requests (1.5): the agreement as given (``body``: its words, its documents), then no title
    deed and no certificates. The last answer, or the agreement's when it was refused."""
    r = c.post(url + "/answer", json={"step_id": "agreement", **body}, headers=headers)
    if r.status_code >= 400:
        return r
    for step in ("title_deed", "certificates"):
        r = c.post(url + "/answer", json={"step_id": step, "none": True}, headers=headers)
    return r


def wait_for(c, url, headers, status, tries=50):
    for _ in range(tries):
        run = c.get(url, headers=headers).json()
        if run["status"] == status:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run never reached {status}: {run['status']}")


RUNS = "/v1/cases/{cid}/playbooks/runs"
RUN = RUNS + "/{rid}"


def as_bob(kc) -> dict:
    """Bob with his own username: the run shows names, but rights are checked by id."""
    return {"Authorization": f"Bearer {kc.tokens(over={'sub': BOB, 'preferred_username': 'bob.test', 'name': 'Bob Test'})['access_token']}"}


def a_case_with_a_contributor(c, kc, role="reader"):
    alice, bob = as_user(kc, ALICE), as_bob(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": role}, headers=alice)
    return cid, alice, bob


@needs_db
def test_deed_intake_asks_reads_asks_waits_for_a_person_and_stores_the_summary(office):
    c, kc, _, docs, captured = office
    cid, alice, bob = a_case_with_a_contributor(c, kc)
    docs.docs[str(uuid.uuid4())] = (Scope.case(uuid.UUID(cid)), "playbook")  # an earlier result: never read
    # which playbooks fit: a sale gets deed intake 1.1, covered, with its routine and its words in every language
    fits = c.get(f"/v1/cases/{cid}/playbooks", headers=bob).json()
    assert [(p["id"], p["covered"], p["version"]) for p in fits] == [("playbook/be-notary/deed-intake", True, "1.7")]
    assert [s["kind"] for s in fits[0]["steps"]] == [*["request"] * 3, *["read"] * 3, "ask", *["check"] * 5, "checkpoint", "produce"]
    assert fits[0]["lists"]["sellers"] == ["name", "address", "register"] and fits[0]["kinds"]["conditions.term"] == "date"
    assert set(fits[0]["text"]) == {"en", "nl", "fr"} and fits[0]["text"]["en"]["labels"]["price"] == "Price"
    assert "{label}" in fits[0]["text"]["nl"]["questions"]["missing"]
    # a reader can't start; a contributor can, in Dutch; the case has no documents, so the playbook asks for them
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=bob).status_code == 403
    assert c.post(f"/v1/cases/{cid}/playbooks/estate-intake/runs", json={}, headers=alice).status_code == 404
    r = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice)
    assert r.status_code == 202
    run = r.json()
    rid = run["id"]
    assert (run["status"], run["step"], run["language"], run["playbook_version"]) == ("waiting", "agreement", "nl", "1.7")
    assert run["steps"]["agreement"]["status"] == "active" and run["steps"]["agreement_read"]["status"] == "pending"
    assert [(t["role"], t["step_id"], t["by"]) for t in run["turns"]] == [("playbook", "agreement", "playbook/be-notary/deed-intake")]
    # the playbook's turn is its meaning, no sentence: each reader's screen asks in their language (decision of 12 November)
    assert (run["turns"][0]["text"], run["turns"][0]["meta"]) == ("", {"kind": "request"})
    # one live run per playbook per case
    r = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice)
    assert r.status_code == 409 and (r.json()["code"], r.json()["params"]["run"]) == ("run.already_going", rid)
    # the chip: the live run per readable case
    chip = c.get("/v1/playbooks/runs/active", headers=bob).json()[cid]
    assert chip["step"] == "agreement" and chip["step_kind"] == "request" and chip["title"]["nl"] == "Akte-intake"
    # answering is a contributor's; saying there is no agreement isn't allowed here; with the document in, the read starts
    assert c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=bob).status_code == 403
    assert c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement", "none": True}, headers=alice).status_code == 422
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "read"}, headers=alice)) == (409, "run.moved_on")
    r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "waiting" and r.json()["step"] == "agreement"  # still no document
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    r = deliver(c, RUN.format(cid=cid, rid=rid), alice, text="Het compromis staat erin.")
    assert r.status_code == 200 and r.json()["status"] == "reading" and r.json()["step"] == "agreement_read" and r.json()["documents"] == [DOC]
    assert '"sellers": [\n    {\n      "name": {"value": <' in captured[-1]["messages"][-1]["content"]  # the playbook's instructions went to the model
    assert captured[-1]["response_format"]["json_schema"]["schema"]["required"][0] == "sellers"  # and the shape the server enforces
    # the model answered; the cadastral data wasn't in the documents, so the playbook asks for it, in Dutch, and waits
    run = wait_for(c, RUN.format(cid=cid, rid=rid), bob, "waiting")
    assert run["step"] == "missing" and run["steps"]["agreement_read"]["status"] == "done" and run["model"] == "Qwen3.8-27B-UD-Q4_K_M.gguf"
    by = {f["id"]: f for f in run["facts"]}
    assert by["price"]["value"] == "EUR 412.500,00" and by["price"]["citations"][0]["filename"] == "akte.pdf" and by["price"]["source"] == "document"
    assert by["cadastral"]["found"] is False and by["cadastral"]["source"] == "none" and by["cadastral"]["confirmed"] is None
    asked = [t for t in run["turns"] if t["step_id"] == "missing"]
    # the ask is about the plain facts the documents lacked; a field empty inside a list's entry (a seller's address) is
    # not asked, it is corrected at the checkpoint, as a founder's is in company formation
    not_found = [f["id"] for f in run["facts"] if not f["found"] and "[" not in f["id"]]
    assert not_found == ["cadastral", "title", "epc", "soil"]
    # one turn says what was found and what not, and asks (handover of 30 October 2026, board 52); a list is one fact,
    # found when it has an entry (board P01: 13 facts, 9 of them read; the lines were 21 and 11, entries and fields counted)
    assert (len(run["facts"]), sum(1 for f in run["facts"] if f["found"])) == (21, 11)
    found, total = 9, 13
    assert [t["meta"] for t in asked] == [{"kind": "ask", "facts": not_found, "found": found, "total": total}]
    assert not_found[0] == "cadastral" and asked[0]["text"] == ""
    # the three requests, each answered (the agreement first without its document), then the ask
    assert [t["role"] for t in run["turns"]] == ["playbook", "user", "user", "playbook", "user", "playbook", "user", "playbook"]
    # the answer: a proposed fact from a person; a fact not asked is refused
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {"price": "1"}}, headers=alice)) == (422, "request.invalid")
    r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {"cadastral": "Gent 5e afd., sectie B, nr. 123"}}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "waiting" and r.json()["step"] == "confirm"
    by = {f["id"]: f for f in r.json()["facts"]}
    assert by["cadastral"]["value"].startswith("Gent") and by["cadastral"]["source"] == "person" and by["cadastral"]["found"] is False
    assert by["cadastral"]["confirmed"] is None  # a person answered; nobody confirmed yet
    assert [t["role"] for t in r.json()["turns"][-2:]] == ["user", "playbook"]
    assert r.json()["turns"][-2]["meta"] == {"answers": {"cadastral": "Gent 5e afd., sectie B, nr. 123"}}  # the values, worded by the screen
    assert r.json()["turns"][-1]["meta"]["kind"] == "checkpoint"  # then the checkpoint says what to check
    # the five checks of 1.3 ran on the way: two sellers, one buyer, the advance within the price, the deed after the
    # agreement, the one condition's term before the deed
    assert {k: v["status"] for k, v in r.json()["checks"].items()} == {
        "a_seller": "holds", "a_buyer": "holds", "deposit_within_price": "holds", "deed_after_agreement": "holds", "conditions_before_deed": "holds"}
    assert r.json()["checks"]["conditions_before_deed"] == {"status": "holds", "rule": "latest(conditions.term) <= deed_deadline",
                                                            "left": "2026-11-02", "right": "2027-01-15", "missing": []}
    assert r.json()["checks"]["deposit_within_price"]["left"] == "41250"
    # the checkpoint: a reader can't confirm; the contributor corrects the price and confirms the rest
    confirm = {"facts": [{"id": "price", "confirmed": "EUR 412.000,00"}]}
    assert c.put(RUN.format(cid=cid, rid=rid) + "/facts", json=confirm, headers=bob).status_code == 403
    assert (lambda r: (r.status_code, r.json()["code"]))(c.put(RUN.format(cid=cid, rid=rid) + "/facts", json={"facts": [{"id": "x", "confirmed": ""}]}, headers=alice)) == (422, "request.invalid")
    r = c.put(RUN.format(cid=cid, rid=rid) + "/facts", json=confirm, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "done" and r.json()["step"] is None and r.json()["confirmed_by"] == "notaris.test"
    by = {f["id"]: f for f in r.json()["facts"]}
    assert by["price"]["confirmed"] == "EUR 412.000,00" and by["price"]["value"] == "EUR 412.500,00"
    assert by["sellers[1].name"]["confirmed"] == "Jan Peeters" and by["sellers[2].name"]["confirmed"] == "Marie Claes"
    assert by["cadastral"]["confirmed"].startswith("Gent") and "sellers" not in by  # a list with entries has no line of its own
    assert r.json()["steps"]["summary"]["status"] == "done" and r.json()["finished_at"]
    # the summary is a document in the case with origin playbook, named after the playbook, the case and the run's version,
    # in the run's language; its text is what 1.0 wrote for the same confirmed facts
    name, text = docs.stored_text
    assert name == "Akte-intake 2026/0417 (1.7)" and text.startswith("Akte-intake 2026/0417\n\nplaybook/be-notary/deed-intake 1.7")
    assert "Prijs: EUR 412.000,00 (akte.pdf p. 2)" in text and "Kadastrale gegevens: Gent 5e afd., sectie B, nr. 123" in text
    assert "Verkoper(s) 1 · Naam: Jan Peeters" in text and "Verkoper(s) 2 · Naam: Marie Claes" in text and "Koper(s) 1 · Naam: Tom Janssens" in text
    assert "Opschortende voorwaarden 1 · Te vervullen tegen: 2 november 2026" in text
    assert "Het voorschot of de waarborg ligt binnen de prijs: klopt" in text  # the price as confirmed: 41.250 within 412.000
    assert "Elke opschortende voorwaarde moet vervuld zijn vóór de uiterste datum van de akte: klopt" in text
    assert docs.stored_provenance == {"playbook": "playbook/be-notary/deed-intake", "version": "1.7", "run": rid}
    assert docs.docs[r.json()["result_document_id"]] == (Scope.case(uuid.UUID(cid)), "playbook")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.put(RUN.format(cid=cid, rid=rid) + "/facts", json=confirm, headers=alice)) == (409, "run.ended")
    assert cid not in c.get("/v1/playbooks/runs/active", headers=alice).json()  # done: no chip
    # the facts' record: one row per version, the model's reading superseded by the person's, never rewritten
    store = c.app.state.runs.get()
    rows = store.fact_rows(uuid.UUID(rid))
    price = [(r_["status"], r_["source"]["kind"], r_["by"]) for r_ in rows if r_["fact_id"] == "price"]
    assert price == [("superseded", "document", "playbook/be-notary/deed-intake"), ("confirmed", "person", "notaris.test")]
    cadastral = [(r_["status"], r_["source"]["kind"]) for r_ in rows if r_["fact_id"] == "cadastral"]
    assert cadastral == [("superseded", "none"), ("superseded", "person"), ("confirmed", "person")]
    title = [(r_["status"], r_["source"]["kind"]) for r_ in rows if r_["fact_id"] == "title"]
    assert title == [("superseded", "none"), ("not_established", "person")]  # asked, left empty, cleared at the checkpoint
    # the access log has every step
    actions = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert {"playbook_started", "playbook_answered", "playbook_confirmed"} <= set(actions)
    # a document the run read is deleted: the run stays, marked out of date; a closed case starts nothing
    assert c.delete(f"/v1/documents/{DOC}?case={cid}", headers=alice).status_code == 204
    assert c.get(RUN.format(cid=cid, rid=rid), headers=alice).json()["out_of_date"] is True
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 403


@needs_db
def test_a_run_is_paused_and_resumed_by_anyone_who_contributes(office):
    c, kc, _, docs, _ = office
    cid, alice, bob = a_case_with_a_contributor(c, kc, "contributor")
    rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).json()["id"]
    r = c.post(RUN.format(cid=cid, rid=rid) + "/pause", headers=bob)
    assert r.status_code == 200 and r.json()["status"] == "paused" and r.json()["paused_by"] == "bob.test" and r.json()["paused_at"]
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(RUN.format(cid=cid, rid=rid) + "/pause", headers=bob)) == (409, "run.paused")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "agreement"}, headers=alice)) == (409, "run.paused")  # paused: nothing advances
    assert c.get("/v1/playbooks/runs/active", headers=alice).json()[cid]["status"] == "paused"  # still shown
    r = c.post(RUN.format(cid=cid, rid=rid) + "/resume", headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "waiting" and r.json()["step"] == "agreement" and r.json()["paused_by"] is None
    actions = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert "playbook_paused" in actions and "playbook_resumed" in actions


@needs_db
def test_a_confirmation_from_an_old_screen_is_refused_and_writes_nothing(office):
    """suveryn-tracker#135: the screen sends every fact's value when a person confirms. A colleague's change a moment
    before would be put back, confirmed, without a word. The confirmation says which state of the facts it saw."""
    c, kc, _, docs, _ = office
    cid, alice, bob = a_case_with_a_contributor(c, kc, "contributor")
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).json()["id"]
    url = RUN.format(cid=cid, rid=rid)
    deliver(c, url, alice)
    wait_for(c, url, alice, "waiting")
    alices = c.post(url + "/answer", json={"step_id": "missing", "facts": {}}, headers=alice).json()  # her screen, at the checkpoint
    assert alices["step"] == "confirm" and alices["facts_seq"] > 0
    as_shown = {"facts": [{"id": f["id"], "confirmed": f["value"]} for f in alices["facts"]], "seen": alices["facts_seq"]}
    # Bob adjusts the price; Alice's screen still shows the old one
    bobs = c.put(url + "/facts/price", json={"value": "EUR 415.000,00"}, headers=bob).json()
    assert bobs["facts_seq"] > alices["facts_seq"]
    r = c.put(url + "/facts", json=as_shown, headers=alice)
    assert r.status_code == 409 and r.json()["code"] == "run.facts_changed" and r.json()["kind"] == "refused"  # a code: the page words it
    now = c.get(url, headers=alice).json()
    price = {f["id"]: f for f in now["facts"]}["price"]
    assert now["status"] == "waiting" and now["step"] == "confirm" and now["confirmed_by"] is None  # nothing was confirmed
    assert price["value"] == "EUR 415.000,00" and price["by"] == "bob.test" and price["confirmed"] is None
    assert now["facts_seq"] == bobs["facts_seq"]  # and nothing was written
    # what stands now, confirmed: Bob's value
    r = c.put(url + "/facts", json={"facts": [{"id": f["id"], "confirmed": f["value"]} for f in now["facts"]], "seen": now["facts_seq"]},
              headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert {f["id"]: f for f in r.json()["facts"]}["price"]["confirmed"] == "EUR 415.000,00"


@needs_db
def test_stop_keeps_confirmed_facts_and_drops_proposed_ones(office):
    c, kc, _, docs, _ = office
    cid, alice, bob = a_case_with_a_contributor(c, kc, "contributor")
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).json()["id"]
    deliver(c, RUN.format(cid=cid, rid=rid), alice)
    run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
    assert run["step"] == "missing"
    # a contributor who didn't start it and doesn't manage the case can't end it; the starter can
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(RUN.format(cid=cid, rid=rid) + "/stop", headers=bob)) == (403, "run.starter_or_manager_only")
    r = c.post(RUN.format(cid=cid, rid=rid) + "/stop", headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "stopped" and r.json()["ended_by"] == "notaris.test"
    store = c.app.state.runs.get()
    statuses = {r_["status"] for r_ in store.fact_rows(uuid.UUID(rid)) if r_["source"]["kind"] == "document"}
    assert statuses == {"superseded"}  # proposed and gone; nothing was confirmed
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(RUN.format(cid=cid, rid=rid) + "/stop", headers=alice)) == (409, "run.ended")
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {}}, headers=alice)) == (409, "run.ended")
    # terminal: a new run can start
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 202


@needs_db
def test_cancel_reverts_confirmed_facts_and_withdraws_the_product(office):
    c, kc, cases, docs, _ = office
    cid, alice, bob = a_case_with_a_contributor(c, kc, "contributor")
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=bob).json()["id"]  # bob starts it
    deliver(c, RUN.format(cid=cid, rid=rid), bob)
    wait_for(c, RUN.format(cid=cid, rid=rid), bob, "waiting")
    c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {"cadastral": "Gent"}}, headers=bob)
    r = c.put(RUN.format(cid=cid, rid=rid) + "/facts", json={"facts": [{"id": "price", "confirmed": "EUR 1"}]}, headers=bob)
    assert r.status_code == 200 and r.json()["status"] == "done"
    doc = r.json()["result_document_id"]
    # done is terminal too: it can't be cancelled through the run... except by design it can, by the starter or the manager
    # (a result that should not have happened); alice manages the case
    r = c.post(RUN.format(cid=cid, rid=rid) + "/cancel", json={"reason": "wrong file"}, headers=alice)
    assert (r.status_code, r.json()["code"]) == (409, "run.ended")  # a finished run is not cancelled: its facts are the case's now (stop/cancel act on live runs)
    # a live run, then: start again, confirm nothing yet, cancel at the checkpoint after answering
    rid2 = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=bob).json()["id"]
    deliver(c, RUN.format(cid=cid, rid=rid2), bob)
    wait_for(c, RUN.format(cid=cid, rid=rid2), bob, "waiting")
    c.post(RUN.format(cid=cid, rid=rid2) + "/answer", json={"step_id": "missing", "facts": {"cadastral": "Gent"}}, headers=bob)
    r = c.post(RUN.format(cid=cid, rid=rid2) + "/cancel", json={"reason": "wrong file"}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["ended_reason"] == "wrong file"
    assert r.json()["ended_by"] == "notaris.test"
    actions = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert "playbook_cancelled" in actions
    assert doc not in getattr(docs, "withdrawn", {})  # the first run's product stands


@needs_db
def test_a_run_is_shown_with_its_facts_marked_and_stores_no_marking(runs):
    """What the source panel marks for a fact is the server's, worked out when the run is shown (``facts.marked``):
    a correction is marked as corrected, and the stored passage carries no marking to go stale."""
    from suveryn_harness.facts import FactCitation

    cid = uuid.uuid4()
    rid = uuid.UUID(runs.create(cid, DEED_INTAKE, [DOC], ALICE, None).id)
    text = "De partijen komen overeen. De prijs bedraagt eenhonderdduizend euro (€ 100.000,00)."
    cite = FactCitation(n=1, document_id=str(DOC), filename="deed.pdf", text=text).model_dump(exclude={"ranges", "facts"})
    runs.write_facts(cid, rid, "read", [dict(fact_id="price", kind="amount", value="€ 100.000", status="proposed",
                                              source={"kind": "document", "citations": [cite]}, by=DEED_INTAKE.id)])
    shown = runs.facts_for_run(rid)[0].citations[0]
    assert [text[a:z] for a, z in shown.ranges] == ["De prijs bedraagt eenhonderdduizend euro (€ 100.000,00)."]
    assert [text[a:z] for a, z in shown.facts] == ["eenhonderdduizend", "100.000,00"]
    stored = runs.fact_rows(rid)[0]["source"]["citations"][0]
    assert "ranges" not in stored and "facts" not in stored
    runs.delete_case(cid)


@needs_db
def test_cancel_supersedes_everything_the_run_established_and_keeps_the_record(runs):
    """Pod check of d0f680e, question Q: a cancelled run leaves nothing of its own as the case's, read
    or confirmed; the rows stay, superseded, so the history is whole (through the store: a routine with
    steps after its checkpoint can be live with confirmed facts)."""
    cid = uuid.uuid4()
    run = runs.create(cid, DEED_INTAKE, [DOC], ALICE, None)
    rid = uuid.UUID(run.id)
    runs.write_facts(cid, rid, "read", [dict(fact_id="price", kind="amount", value="1", status="proposed",
                                              source={"kind": "document", "citations": []}, by=DEED_INTAKE.id),
                                         dict(fact_id="deposit", kind="amount", value="2", status="proposed",
                                              source={"kind": "document", "citations": []}, by=DEED_INTAKE.id)])
    first = runs.current_versions(rid)["price"]["id"]
    runs.write_facts(cid, rid, "confirm", [dict(fact_id="price", kind="amount", value="2", status="confirmed",
                                                 source={"kind": "person", "checkpoint": True}, by="alice", replaces=first)])
    assert [f.confirmed for f in runs.facts_for_run(rid)] == ["2", None]
    assert runs.end(rid, "cancelled", "alice", "oops") and runs.discard_all(rid) == 2  # the confirmed price and the proposed deposit
    facts = runs.facts_for_run(rid)
    assert facts[0].confirmed is None and facts[0].value == "1"  # no longer the case's; what was read is still shown
    rows = [(r["fact_id"], r["status"]) for r in runs.fact_rows(rid)]
    assert rows == [("price", "superseded"), ("deposit", "superseded"), ("price", "superseded")]  # kept, nothing rewritten
    runs.delete_case(cid)


@needs_db
def test_an_admin_switches_a_playbook_off_and_it_leaves_every_case(office):
    c, kc, _, docs, _ = office
    alice, admin = as_user(kc, ALICE), admin_headers(kc)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    # the admin's list: every installed playbook, active unless switched off
    assert c.get("/v1/admin/playbooks", headers=alice).status_code == 403
    listed = c.get("/v1/admin/playbooks", headers=admin).json()
    # the official playbook, then the installed pack's (the fictional test pack, conftest.py: SUVERYN_PACKS_DIR)
    assert [(p["id"], p["active"], p["case_types"]) for p in listed] == [
        ("playbook/be-notary/deed-intake", True, ["sale"]), ("playbook/be-test/care-mandate", True, ["care-mandate"]),
        ("playbook/be-test/company-formation", True, ["company-formation"])]
    assert c.put("/v1/admin/playbooks/deed-intake", json={"active": False}, headers=alice).status_code == 403
    assert c.put("/v1/admin/playbooks/nope", json={"active": False}, headers=admin).status_code == 404
    r = c.put("/v1/admin/playbooks/deed-intake", json={"active": False}, headers=admin)
    assert r.status_code == 200 and r.json()["active"] is False
    # off: it isn't offered in the case and can't be started
    assert c.get(f"/v1/cases/{cid}/playbooks", headers=alice).json() == []
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 404
    # on again
    assert c.put("/v1/admin/playbooks/deed-intake", json={"active": True}, headers=admin).json()["active"] is True
    assert [p["id"] for p in c.get(f"/v1/cases/{cid}/playbooks", headers=alice).json()] == ["playbook/be-notary/deed-intake"]


@needs_db
def test_a_run_fails_by_kind_when_the_answer_isnt_the_table(runs):
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text="Ik weet het niet."))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
        assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"document_ids": [str(uuid.uuid4())]}, headers=alice).status_code == 404
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"document_ids": [DOC]}, headers=alice).json()["id"]
        deliver(c, RUN.format(cid=cid, rid=rid), alice)
        run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "failed")
        assert run["failure"] == {"kind": "refused", "code": "run.answer_unreadable", "params": {}} and "error" not in run and run["facts"] == [] and run["step"] == "agreement_read"


@needs_db
def test_an_unreadable_answer_is_asked_for_once_more_with_a_stricter_reminder(runs):
    """Review 2026-10-17: the second attempt carries the reminder; a readable second answer makes the run."""
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    captured: list = []
    plain = llm_transport(captured, text="Ik weet het niet.")
    good = llm_transport(captured, text=TABLE)
    transport = httpx.MockTransport(lambda r: (good if "could not be read" in r.content.decode() else plain).handler(r))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=transport)
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).json()["id"]
        deliver(c, RUN.format(cid=cid, rid=rid), alice)
        run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
        # each of the three reads asked twice: the first answer can't be read, the second, reminded, can
        assert len(captured) == 6 and all("could not be read" in captured[i]["messages"][-1]["content"] for i in (1, 3, 5))
        assert captured[1]["max_tokens"] == 6144 and len(run["facts"]) == 21  # READ_TOKENS: the JSON with room for a list; 1.3's lines


@needs_db
def test_a_run_reading_when_the_gateway_stopped_is_failed_at_the_next_start(runs):
    """Review 2026-10-17: a restart used to leave a run spinning forever."""
    cid = uuid.uuid4()
    run = runs.create(cid, DEED_INTAKE, [DOC], ALICE, None)
    runs.set_step(uuid.UUID(run.id), "read", "reading", {"read": __import__("suveryn_api_gateway.playbooks", fromlist=["StepState"]).StepState(status="active")})
    assert runs.interrupt(30 * 60) == 0  # the sweep: not stale yet
    assert runs.interrupt(0) == 1        # start-up: every reading run is dead
    got = runs.get(uuid.UUID(run.id), cid)
    assert got.status == "failed" and got.failure.model_dump() == {"kind": "unavailable", "code": "run.interrupted", "params": {}} and got.finished_at is not None
    assert runs.interrupt(0) == 0
    runs.delete_case(cid)


@needs_db
def test_starting_runs_shares_the_chat_rate_limit(runs):
    from suveryn_api_gateway.ratelimit import RateLimits
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text=TABLE))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory(),
                     rate_limits=RateLimits(chat=2))
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        codes = []
        for i in range(3):  # one run per case: a case has one live run of a playbook
            cid = c.post("/v1/cases", json={**NEW, "reference": f"2026/{i}"}, headers=alice).json()["id"]
            codes.append(c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code)
        assert codes == [202, 202, 429]


@needs_db
def test_a_reading_that_ends_after_its_run_was_stopped_writes_nothing(runs):
    """A run stopped or cancelled while it read: what the read found comes too late and is not kept."""
    from suveryn_api_gateway.playbooks import StepState

    cid = uuid.uuid4()
    rid = uuid.UUID(runs.create(cid, DEED_INTAKE, [DOC], ALICE, None).id)
    fact = [dict(fact_id="price", kind="amount", value="1", status="proposed", source={"kind": "none"}, by="x")]
    runs.set_step(rid, "read", "reading", {"read": StepState(status="active")})
    assert runs.end(rid, "stopped", ALICE)
    assert runs.write_facts(cid, rid, "read", fact, reading=True) is False and runs.facts_for_run(rid) == []
    other_case = uuid.uuid4()  # a run still reading keeps what it found
    other = uuid.UUID(runs.create(other_case, DEED_INTAKE, [DOC], ALICE, None).id)
    runs.set_step(other, "read", "reading", {"read": StepState(status="active")})
    assert runs.write_facts(other_case, other, "read", fact, reading=True) is True and len(runs.facts_for_run(other)) == 1


@needs_db
def test_store_deletes_runs_with_the_case(runs):
    cid = uuid.uuid4()
    run = runs.create(cid, DEED_INTAKE, [DOC], ALICE, None, "nl", ALICE)
    rid, conv = uuid.UUID(run.id), uuid.UUID(run.conversation_id)
    assert runs.get(rid, cid).status == "waiting" and runs.get(rid, uuid.uuid4()) is None
    # the run is a conversation in its case (decision, 30 October 2026): titled with the playbook, shared, its starter's;
    # its title in every language, so each reader's list shows theirs (decision of 12 November 2026)
    row = runs._execute("SELECT title, case_id, shared, owner, run_id, titles FROM conversations WHERE id = %s", (conv,)).fetchone()
    assert row == (DEED_INTAKE.wording("nl").title, cid, True, ALICE, rid,
                   {"en": "Deed intake", "nl": DEED_INTAKE.wording("nl").title, "fr": DEED_INTAKE.wording("fr").title})
    # a playbook's turn is its meaning, never a sentence: one with text, or of no known kind, is refused
    with pytest.raises(ValueError):
        runs.say(run, "playbook", DEED_INTAKE.id, "Upload the agreement.", "agreement", {"kind": "request"})
    with pytest.raises(ValueError):
        runs.say(run, "playbook", DEED_INTAKE.id, "", "agreement", {"kind": "a sentence"})
    runs.say(run, "playbook", DEED_INTAKE.id, "", "agreement", {"kind": "request"}, once=True)
    runs.say(run, "playbook", DEED_INTAKE.id, "", "agreement", {"kind": "request"}, once=True)  # the same turn again: once
    runs.say(run, "playbook", DEED_INTAKE.id, "", "agreement", {"kind": "unplaced"}, once=True)  # another meaning: kept
    runs.write_facts(cid, rid, "read", [dict(fact_id="price", kind="amount", value="1", status="proposed", source={"kind": "none"}, by="x")])
    assert [t.meta.kind for t in runs.get(rid, cid).turns] == ["request", "unplaced"] and len(runs.fact_rows(rid)) == 1
    assert runs.delete_case(cid) == 1 and runs.list(cid) == []
    assert runs.turns_of(conv) == [] and runs.fact_rows(rid) == []  # the conversation, its turns and the facts went with the case
    assert runs._execute("SELECT count(*) FROM conversations WHERE id = %s", (conv,)).fetchone()[0] == 0


@needs_db
@pytest.mark.parametrize("ending", ["stop", "cancel"])
def test_a_run_stopped_while_it_reads_ends_its_reading_at_once(runs, ending):
    """The code review of 25 November: stop or cancel left the model reading to the end, holding the card and the
    person's place among the runs reading. Now the reading ends at once: the model call is abandoned, the place is
    given back, and nothing it would have read is written."""
    import asyncio
    import threading

    from suveryn_api_gateway.routes import playbooks as route

    asked, abandoned, never = threading.Event(), threading.Event(), threading.Event()
    plain = llm_transport([], text=TABLE).handler

    async def busy(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            asked.set()
            try:
                while not never.is_set():  # a model that would take its time
                    await asyncio.sleep(0.02)
            except asyncio.CancelledError:
                abandoned.set()  # the gateway let go of the call: llama-server ends a request whose connection closed
                raise
        return plain(request)

    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(busy))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    try:
        with TestClient(app) as c:
            alice = as_user(kc, ALICE)
            cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
            docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
            run = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).json()
            url = RUN.format(cid=cid, rid=run["id"])
            assert deliver(c, url, alice).json()["status"] == "reading" and asked.wait(5)
            assert route.slots_of(app).taken  # her place among the runs reading
            r = c.post(url + "/stop", headers=alice) if ending == "stop" else c.post(url + "/cancel", json={"reason": "wrong case"}, headers=alice)
            assert r.status_code == 200 and r.json()["status"] == ("stopped" if ending == "stop" else "cancelled")
            assert abandoned.wait(5)
            for _ in range(100):
                if not route.slots_of(app).taken:
                    break
                time.sleep(0.02)
            assert not route.slots_of(app).taken and not app.state.reading
            assert not c.get(url, headers=alice).json()["facts"] or all(f["status"] != "proposed" for f in c.get(url, headers=alice).json()["facts"])
    finally:
        never.set()


@needs_db
def test_only_so_many_runs_read_at_once(runs, monkeypatch):
    """The audit of 25 October 2026, finding 3: nothing bounded how many runs read at the same time.
    Two of one person's and four in all; one more is refused with a sentence until one finishes."""
    import asyncio
    import threading

    from suveryn_api_gateway.routes import playbooks as route

    monkeypatch.setattr(route, "MAX_RUNS_PER_USER", 2)
    monkeypatch.setattr(route, "MAX_RUNS", 3)
    release = threading.Event()
    plain = llm_transport([], text=TABLE).handler

    async def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            while not release.is_set():  # the model is busy until the test says
                await asyncio.sleep(0.02)
        return plain(request)

    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(slow))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    try:
        with TestClient(app) as c:
            alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
            n = iter(range(100))

            def start(who):  # a case per run (one live run of a playbook per case); its document is in, and the
                # request answered (it always asks first), so the read starts
                cid = c.post("/v1/cases", json={**NEW, "reference": f"2026/{next(n)}"}, headers=alice).json()["id"]
                c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
                docs.docs[str(uuid.uuid4())] = (Scope.case(uuid.UUID(cid)), "uploaded")
                run = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=who).json()
                return deliver(c, RUN.format(cid=cid, rid=run["id"]), who), cid

            codes = [start(alice)[0].status_code for _ in range(3)]
            assert codes == [200, 200, 429]  # two of hers at once
            r, cid = start(bob)
            assert r.status_code == 200  # someone else's first: three in all
            rid = r.json()["id"]
            r, busy_cid = start(bob)
            assert r.status_code == 429 and r.json()["code"] == "run.too_many"  # the appliance's three
            busy = c.get(RUNS.format(cid=busy_cid), headers=alice).json()[0]
            assert busy["status"] == "failed" and busy["failure"]["code"] == "run.too_many"  # the refused run is a record too; start it again later
            release.set()
            wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
            for _ in range(50):  # every place given back once the readings end
                if not route.slots_of(app).taken:
                    break
                time.sleep(0.05)
            assert not route.slots_of(app).taken
            assert start(alice)[0].status_code == 200
    finally:
        release.set()


# ------------------------------------------------------------------ a playbook is a conversation (handover of 30 October 2026)

@pytest.fixture
def talking(runs):
    """An office whose model reads the table, and maps an answer in words to what ``replies`` holds next."""
    import json as _json
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    replies: list[str] = []
    reading = llm_transport([], text=TABLE).handle_request

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions") and "answered in their own words" in _json.loads(request.content)["messages"][-1]["content"]:
            reply = replies.pop(0)  # the words the model answers, or a whole response (one that can't be read)
            return reply if isinstance(reply, httpx.Response) else streamed(reply)
        return reading(request)

    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(handler))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases, runs=runs,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        yield c, kc, docs, replies


@needs_db
def test_an_answer_in_words_whose_model_answer_cant_be_read_is_an_unplanned_failure_not_a_model_that_is_down(talking):
    """suveryn-tracker#164: the model answered, so it isn't down: nobody planned for it, and the log has the reference."""
    c, kc, docs, replies = talking
    cid, alice, _ = a_case_with_a_contributor(c, kc, role="contributor")
    run = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice).json()
    url = RUN.format(cid=cid, rid=run["id"])
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    c.post(url + "/say", json={"text": "Hier is het compromis.", "documents": [DOC]}, headers=alice)
    for step in ("title_deed", "certificates"):
        c.post(url + "/answer", json={"step_id": step, "none": True}, headers=alice)
    assert wait_for(c, url, alice, "waiting")["step"] == "missing"
    garbled = model_garbled()
    replies.append(garbled)  # an answer in words, and the model sends back what isn't an answer
    r = c.post(url + "/say", json={"text": "Kadaster: Gent 5e afd., sectie B, nr. 123."}, headers=alice)
    assert (r.status_code, r.json()["code"]) == (500, "system.internal") and r.json()["params"]["ref"]


@needs_db
def test_a_reading_whose_model_answer_cant_be_read_fails_the_run_with_a_reference(runs):
    """The other way to the model, a read step: the run fails as an unplanned failure, not as a model that is down (#164)."""
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    usual = llm_transport([]).handle_request
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(
        lambda request: model_garbled()
        if request.url.path.endswith("/chat/completions") else usual(request)))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases, runs=runs,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        cid, alice, _ = a_case_with_a_contributor(c, kc)
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice).json()["id"]
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        deliver(c, RUN.format(cid=cid, rid=rid), alice, text="Het compromis.")
        failed = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "failed")
        assert (failed["failure"]["kind"], failed["failure"]["code"]) == ("internal", "system.internal") and failed["failure"]["params"]["ref"]


@needs_db
def test_a_reading_that_cant_start_fails_its_run_at_once_with_a_reference(runs, monkeypatch, caplog):
    """suveryn-tracker#275: a run marked reading whose documents couldn't be looked up or stored stayed reading, with
    nothing behind it, until the hourly sweep called it interrupted by a restart. Now it fails at once."""
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text=TABLE))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases, runs=runs,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())

    from suveryn_api_gateway.playbook_runtime import Runtime
    walk_on, look_up, marked = Runtime.advance, Runtime.documents_to_read, []

    def advance(self, run, playbook, reference):
        step = walk_on(self, run, playbook, reference)
        marked.append(step is not None)  # the run is now marked reading
        return step

    def documents_to_read(self, run, step):
        if any(marked):  # the gateway looking up what the reading reads, once the run is marked reading
            raise OSError("/var/lib/suveryn/notary-ghent: nobody planned for this")
        return look_up(self, run, step)
    monkeypatch.setattr(Runtime, "advance", advance)
    monkeypatch.setattr(Runtime, "documents_to_read", documents_to_read)
    with TestClient(app) as c:
        cid, alice, _ = a_case_with_a_contributor(c, kc)
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "en"}, headers=alice).json()["id"]
        url = RUN.format(cid=cid, rid=rid)
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        r = deliver(c, url, alice, text="The agreement.")
        failed = c.get(url, headers=alice).json()
    assert r.status_code == 200 and failed["status"] == "failed"  # at once, not reading
    assert (failed["failure"]["kind"], failed["failure"]["code"]) == ("internal", "system.internal")
    ref = failed["failure"]["params"]["ref"]
    line = next(rec.getMessage() for rec in caplog.records if ref in rec.getMessage())
    assert "OSError at " in line and "documents_to_read" in line and "notary-ghent" not in caplog.text


@needs_db
def test_a_run_that_cant_go_on_after_its_reading_fails_at_once_with_a_reference(runs, monkeypatch, caplog):
    """The code review of 25 November: a step that failed after the model's answer was in left the run reading
    until the hourly sweep called it interrupted by a restart. Now it fails at once, as nobody planned for it."""
    from suveryn_api_gateway.playbook_runtime import Runtime
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text=TABLE))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases, runs=runs,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    walk_on = Runtime.advance

    def advance(self, run, playbook, reference):
        if run.status == "reading":  # after the reading: what nobody planned for
            raise OSError("/var/lib/suveryn/notary-ghent: nobody planned for this")
        return walk_on(self, run, playbook, reference)
    monkeypatch.setattr(Runtime, "advance", advance)
    with TestClient(app) as c:
        cid, alice, _ = a_case_with_a_contributor(c, kc)
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice).json()["id"]
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        deliver(c, RUN.format(cid=cid, rid=rid), alice, text="Het compromis.")
        failed = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "failed")
    assert (failed["failure"]["kind"], failed["failure"]["code"]) == ("internal", "system.internal")
    ref = failed["failure"]["params"]["ref"]
    line = next(r.getMessage() for r in caplog.records if ref in r.getMessage())
    assert "OSError at " in line and "advance" in line and "notary-ghent" not in caplog.text


@needs_db
def test_people_answer_and_correct_a_playbook_in_words(talking):
    """The run is a conversation: the documents come with a turn, an answer in words is mapped to the facts
    asked, what can't be placed is asked again in words, a correction makes a new version from that person,
    and pausing is a line in the thread."""
    c, kc, docs, replies = talking
    cid, alice, bob = a_case_with_a_contributor(c, kc, role="contributor")
    run = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice).json()
    url = RUN.format(cid=cid, rid=run["id"])
    assert run["conversation_id"]
    # the request: the documents come in with the person's turn, as attachments
    assert c.post(url + "/say", json={"documents": [DOC]}, headers=alice).status_code == 404  # not in the case yet
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    r = c.post(url + "/say", json={"text": "Hier is het compromis.", "documents": [DOC]}, headers=alice)
    assert r.status_code == 200 and (r.json()["status"], r.json()["step"]) == ("waiting", "title_deed")  # the next request
    for step in ("title_deed", "certificates"):
        r = c.post(url + "/answer", json={"step_id": step, "none": True}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "reading"
    assert [{"documentId": DOC, "filename": "akte.pdf"}] in [t["meta"].get("attachments") for t in r.json()["turns"]]
    run = wait_for(c, url, alice, "waiting")
    assert run["step"] == "missing" and run["turns"][-1]["meta"]["kind"] == "ask"
    # an answer the model can't place: the playbook asks again in words, the step waits
    replies.append("NONE")
    run = c.post(url + "/say", json={"text": "Dat weet ik niet zo goed."}, headers=bob).json()
    assert run["step"] == "missing" and run["turns"][-1]["meta"]["kind"] == "unplaced" and run["turns"][-2]["by"] == "bob.test"
    # an answer it can place: a proposed fact from that person, and on to the checkpoint
    replies.append("cadastral: Gent 5e afd., sectie B, nr. 123\nprice: 1")  # price wasn't asked: ignored
    run = c.post(url + "/say", json={"text": "Kadaster: Gent 5e afd., sectie B, nr. 123."}, headers=bob).json()
    facts = {f["id"]: f for f in run["facts"]}
    assert run["step"] == "confirm" and facts["cadastral"]["value"].startswith("Gent") and facts["cadastral"]["by"] == "bob.test"
    assert facts["price"]["value"] == "EUR 412.500,00" and facts["price"]["was"] is None
    assert run["turns"][-1]["meta"]["kind"] == "checkpoint"
    # a correction in words: a new version, the value as read kept as ``was``; the playbook says what changed
    replies.append("price: EUR 415.000,00")
    run = c.post(url + "/say", json={"text": "De prijs is EUR 415.000,00."}, headers=alice).json()
    facts = {f["id"]: f for f in run["facts"]}
    assert facts["price"]["value"] == "EUR 415.000,00" and facts["price"]["was"] == "EUR 412.500,00" and facts["price"]["confirmed"] is None
    assert run["turns"][-1]["meta"] == {"kind": "changed", "fact": "price", "value": "EUR 415.000,00"} and run["step"] == "confirm"
    # "not known yet" in words, of a fact that is unknown already (VM regression 03c8f74, finding 8): said so, not "unplaced"
    assert facts["soil"]["value"] == ""
    replies.append("NONE")
    run = c.post(url + "/say", json={"text": "Bodemattest: nog niet bekend."}, headers=alice).json()
    assert run["turns"][-1]["meta"] == {"kind": "already_unknown", "facts": ["soil"]} and run["step"] == "confirm"
    # a card at the checkpoint (handover of 31 October 2026): the same value says it was checked, no turn;
    # a changed one is a version and a line; a fact that isn't in the run is refused
    turns = len(run["turns"])
    run = c.put(url + "/facts/price", json={"value": "EUR 415.000,00"}, headers=bob).json()
    facts = {f["id"]: f for f in run["facts"]}
    assert len(run["turns"]) == turns and facts["price"]["by"] == "bob.test" and facts["price"]["at"]
    run = c.put(url + "/facts/deposit", json={"value": "EUR 41.500,00"}, headers=bob).json()
    assert run["turns"][-1]["meta"] == {"kind": "changed", "fact": "deposit", "value": "EUR 41.500,00"}
    assert c.put(url + "/facts/nothing", json={"value": "1"}, headers=bob).status_code == 404
    assert (lambda r: (r.status_code, r.json()["code"]))(c.put(url + "/facts/price", json={"value": ""}, headers=bob)) == (422, "request.invalid")
    # pausing is a line in the thread; a paused run takes nothing said
    run = c.post(url + "/pause", headers=bob).json()
    assert run["turns"][-1]["meta"] == {"kind": "paused"} and run["turns"][-1]["by"] == "bob.test"
    assert (lambda r: (r.status_code, r.json()["code"]))(c.post(url + "/say", json={"text": "x"}, headers=alice)) == (409, "run.paused")


@needs_db
def test_the_request_asks_even_when_the_case_has_documents_and_the_question_is_written_once(office):
    """VM regression e0f2e26: a document left in the case was read as the agreement without a word (question 1:
    the request always asks first); two answers at the same moment wrote the playbook's question twice (finding
    2); a start without a language takes the caller's (finding 11)."""
    c, kc, _, docs, _ = office
    cid, alice, bob = a_case_with_a_contributor(c, kc, role="contributor")
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    run = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers={**alice, "Accept-Language": "fr-BE,fr;q=0.9"}).json()
    assert run["status"] == "waiting" and run["step"] == "agreement" and run["language"] == "fr"
    url = RUN.format(cid=cid, rid=run["id"])
    assert deliver(c, url, alice, text="Celui du dossier.").json()["status"] == "reading"
    run = wait_for(c, url, alice, "waiting")
    asks = [t for t in run["turns"] if t["meta"].get("kind") == "ask"]
    assert len(asks) == 1
    from suveryn_api_gateway.playbooks import RunStore
    store = RunStore(URL)
    try:
        again = store.say(store.get(uuid.UUID(run["id"]), uuid.UUID(cid)), "playbook", asks[0]["by"], asks[0]["text"], asks[0]["step_id"],
                          asks[0]["meta"], once=True)
        assert again.seq == asks[0]["seq"]  # the same line again: not written
    finally:
        store.close()


FORMATION_ANSWER = json.dumps({
    "company_name": {"value": "Suveryn Labs BV", "sources": [1]}, "seat": {"value": None, "sources": []},
    "object": {"value": None, "sources": []}, "contribution": {"value": "EUR 412.500,00", "sources": [1]},
    "contribution_in_kind": {"value": None, "sources": []},
    "shares": {"value": None, "sources": []}, "directors": {"value": None, "sources": []}, "representation": {"value": None, "sources": []},
    "fiscal_year": {"value": None, "sources": []}, "general_meeting": {"value": None, "sources": []},
    "plan_date": {"value": None, "sources": []}, "financial_plan": {"value": None, "sources": []},
    "contribution_kind": {"value": None, "sources": []}, "in_kind_value": {"value": None, "sources": []}, "auditor": {"value": None, "sources": []},
    "bank_certificate": {"value": None, "sources": []}, "certified_amount": {"value": "EUR 412.500,00", "sources": [1]},
    "founders": [{"name": {"value": "Filip Tack", "sources": [1]}, "register_number": {"value": None, "sources": []},
                  "born": {"value": None, "sources": []}, "address": {"value": "Kerkstraat 12, Gent", "sources": [1]},
                  "shares": {"value": "600", "sources": [1]}, "contribution": {"value": "EUR 412.500,00", "sources": [1]}}],
})


def through_the_requests(c, cid, rid, alice, docs, kind="In cash"):
    """Company formation 1.3 asks for the identity documents and the financial plan by name, asks how the
    founders contribute (the stub's plan doesn't say), then for the bank certificate (money) or the reports
    (in kind); one uploaded document answers each request, named explicitly."""
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    for step in ("identity", "plan"):
        run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
        assert run["step"] == step, run["step"]
        r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": step, "documents": [DOC]}, headers=alice)
        assert r.status_code == 200 and r.json()["status"] == "reading", r.json()
    run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
    assert run["step"] == "kind_known" and run["turns"][-1]["meta"]["facts"] == ["contribution_kind"]
    # the choice, in the pack's words for an option (the UI's buttons send the id; words are mapped too)
    r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "kind_known", "facts": {"contribution_kind": kind}}, headers=alice)
    assert r.status_code == 200
    run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
    step = "bank" if kind != "In kind" else "reports"
    assert run["step"] == step, (run["step"], [t["text"] for t in run["turns"][-3:]])
    r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": step, "documents": [DOC]}, headers=alice)
    assert r.status_code == 200
    return wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")


@needs_db
def test_company_formation_reads_a_list_of_founders_and_a_person_adds_one(runs):
    """Format 3 (docs/design/playbooks.md, "Lists"): the founders come back as entries named by path, each value
    checked by kind; a person adds a second founder at the checkpoint; the summary shows the entries."""
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    captured: list = []
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport(captured, text=FORMATION_ANSWER))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        cid = c.post("/v1/cases", json={**NEW, "type": "company-formation", "name": "Oprichting Suveryn Labs"}, headers=alice).json()["id"]
        fits = c.get(f"/v1/cases/{cid}/playbooks", headers=alice).json()
        assert [p["id"] for p in fits] == ["playbook/be-test/company-formation"]  # the installed pack's (conftest.py)
        assert fits[0]["lists"] == {"founders": ["name", "address", "shares", "contribution"]}
        assert fits[0]["kinds"]["founders.shares"] == "number" and fits[0]["kinds"]["certified_amount"] == "amount"
        assert fits[0]["choices"] == {"contribution_kind": ["cash", "in_kind", "mixed"]} and fits[0]["kinds"]["contribution_kind"] == "choice"
        assert fits[0]["text"]["nl"]["labels"]["contribution_kind.in_kind"] == "In natura" and fits[0]["text"]["nl"]["steps"]["bank"] == "Bankattest"
        assert fits[0]["text"]["nl"]["labels"]["founders.contribution"] == "Inbreng"
        rid = c.post(f"/v1/cases/{cid}/playbooks/company-formation/runs", json={"language": "nl"}, headers=alice).json()["id"]
        run = through_the_requests(c, cid, rid, alice, docs)
        assert run["step"] == "missing"
        # three reads, each aimed at its request's document and asking for its own facts only; the reports' read never ran
        shapes = [b["response_format"]["json_schema"]["schema"]["properties"] for b in captured if "response_format" in b]
        assert [sorted(s) for s in shapes] == [["founders"], sorted(["company_name", "seat", "contribution_kind", "contribution", "shares"]),
                                              ["bank_certificate", "certified_amount"]]
        assert shapes[0]["founders"]["type"] == "array" and run["requested"] == {"identity": [DOC], "plan": [DOC], "bank": [DOC]}
        assert shapes[1]["contribution_kind"]["properties"]["value"] == {"enum": ["cash", "in_kind", "mixed", None]}
        # the choice, answered in words, is its option; the in-kind branch was skipped and the thread says why
        by = {f["id"]: f for f in run["facts"]}
        assert by["contribution_kind"]["value"] == "cash" and by["contribution_kind"]["source"] == "person"
        assert run["steps"]["reports"] == {**run["steps"]["reports"], "status": "skipped", "because": "contribution_kind != cash; cash"}
        assert run["steps"]["reports_read"]["status"] == "skipped" and "contribution_in_kind" not in by and "auditor" not in by
        skipped = [t for t in run["turns"] if t["meta"].get("kind") == "skipped_step"]
        assert [(t["meta"]["step"], t["meta"]["value"]) for t in skipped] == [("reports", "cash"), ("reports_read", "cash")]
        assert skipped[0]["text"] == "" and skipped[0]["meta"]["fact"] == "contribution_kind"  # worded by the screen
        by = {f["id"]: f for f in run["facts"]}
        # the entries, by path; the number of shares isn't in the cited passage: *Check*
        assert by["founders[1].name"]["value"] == "Filip Tack" and by["founders[1].name"]["source"] == "document"
        assert by["founders[1].shares"]["issues"] == ["600"] and by["founders[1].contribution"]["issues"] == []
        assert "founders" not in by  # a list with entries has no "none" of its own
        asked = [t for t in run["turns"] if t["step_id"] == "missing"][0]
        assert "founders" not in asked["meta"]["facts"] and "seat" in asked["meta"]["facts"]
        # the ask: the seat, in words; the rest stays unknown
        r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {"seat": "Sint-Jansvest 18/1, 9000 Gent"}}, headers=alice)
        assert r.status_code == 200 and r.json()["step"] == "confirm"
        # the checks ran on the way to the checkpoint: computed by the server on the values as they stand
        checks = r.json()["checks"]
        assert set(checks) == {"shares_add_up", "contributions_add_up", "bank_certifies_the_contribution", "a_founder"}  # the money branch: every check
        assert checks["a_founder"]["status"] == "holds" and checks["bank_certifies_the_contribution"] == {
            "status": "holds", "rule": "certified_amount == contribution", "left": "412500", "right": "412500", "missing": []}
        assert checks["contributions_add_up"]["status"] == "holds"              # one founder, 412.500 = 412.500
        assert checks["shares_add_up"] == {"status": "open", "rule": "sum(founders.shares) == shares", "left": "600", "right": "", "missing": ["shares"]}
        assert r.json()["turns"][-1]["meta"]["failing"] == 0
        # at the checkpoint a person adds a second founder, value by value, on a path the read never made
        r = c.put(RUN.format(cid=cid, rid=rid) + "/facts/founders[2].name", json={"value": "Anna Peeters"}, headers=alice)
        assert r.status_code == 200
        r = c.put(RUN.format(cid=cid, rid=rid) + "/facts/founders[2].shares", json={"value": "400"}, headers=alice)
        assert r.status_code == 200
        by = {f["id"]: f for f in r.json()["facts"]}
        assert by["founders[2].name"]["source"] == "person" and by["founders[2].shares"]["value"] == "400"
        assert (r.json()["turns"][-1]["text"], r.json()["turns"][-1]["meta"]) == ("", {"kind": "changed", "fact": "founders[2].shares", "value": "400"})
        # a value given at the checkpoint recomputes the checks: the shares issued, filled in, settles one and fails none
        r = c.put(RUN.format(cid=cid, rid=rid) + "/facts/shares", json={"value": "1.000"}, headers=alice)
        assert r.json()["checks"]["shares_add_up"] == {"status": "holds", "rule": "sum(founders.shares) == shares", "left": "1000", "right": "1000", "missing": []}
        r = c.put(RUN.format(cid=cid, rid=rid) + "/facts/founders[2].contribution", json={"value": "EUR 10.000,00"}, headers=alice)
        assert r.json()["checks"]["contributions_add_up"]["status"] == "fails" and r.json()["checks"]["contributions_add_up"]["left"] == "422500"
        assert c.put(RUN.format(cid=cid, rid=rid) + "/facts/founders[2].age", json={"value": "x"}, headers=alice).status_code == 404
        assert c.put(RUN.format(cid=cid, rid=rid) + "/facts/founders", json={"value": "x"}, headers=alice).status_code == 404
        assert (lambda r: (r.status_code, r.json()["code"]))(c.put(RUN.format(cid=cid, rid=rid) + "/facts/contribution_kind", json={"value": "gold"}, headers=alice)) == (422, "run.value_invalid")  # not an option
        r = c.put(RUN.format(cid=cid, rid=rid) + "/facts/contribution_kind", json={"value": "Cash and in kind"}, headers=alice)
        assert r.status_code == 200 and {f["id"]: f for f in r.json()["facts"]}["contribution_kind"]["value"] == "mixed"
        assert len(r.json()["checks"]) == 4  # mixed: there is money too, so the bank's check and the contributions' stay on
        r = c.put(RUN.format(cid=cid, rid=rid) + "/facts/contribution_kind", json={"value": "In kind"}, headers=alice)
        assert set(r.json()["checks"]) == {"shares_add_up", "a_founder"}  # in kind: the two money checks have no result
        r = c.put(RUN.format(cid=cid, rid=rid) + "/facts/contribution_kind", json={"value": "cash"}, headers=alice)
        assert r.status_code == 200 and len(r.json()["checks"]) == 4
        # confirm: the entries, a third founder given straight in the confirm body, the shares corrected; the case manager
        # confirms (by: manager), a contributor is refused even though they may correct
        confirm = {"facts": [{"id": "founders[1].shares", "confirmed": "650"}, {"id": "founders[3].name", "confirmed": "Tom Janssens"},
                             {"id": "founders[3].shares", "confirmed": "50"}]}
        bob = as_bob(kc)
        c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "contributor"}, headers=alice)
        assert c.put(RUN.format(cid=cid, rid=rid) + "/facts/seat", json={"value": "Sint-Jansvest 18, Gent"}, headers=bob).status_code == 200
        assert (lambda r: (r.status_code, r.json()["code"]))(c.put(RUN.format(cid=cid, rid=rid) + "/facts", json=confirm, headers=bob)) == (403, "run.manager_only")
        r = c.put(RUN.format(cid=cid, rid=rid) + "/facts", json=confirm, headers=alice)
        assert r.status_code == 200 and r.json()["status"] == "done"
        by = {f["id"]: f for f in r.json()["facts"]}
        assert by["founders[1].shares"]["confirmed"] == "650" and by["founders[2].name"]["confirmed"] == "Anna Peeters"
        assert by["founders[3].name"]["confirmed"] == "Tom Janssens"
        assert r.json()["checks"]["shares_add_up"]["status"] == "fails"   # 650 + 400 + 50 against 1000, on the confirmed values; confirmed all the same
        name, text = docs.stored_text
        assert "De aandelen van de oprichters tellen op tot de uitgegeven aandelen: klopt niet (1100 / 1000)" in text
        assert "De bank attesteert de inbreng in geld: klopt" in text and "Er is minstens één oprichter: klopt" in text
        assert name == "Oprichting (test) 2026/0417 (1.0)"
        assert "Oprichter(s) 1 · Naam: Filip Tack (akte.pdf p. 2)" in text and "Oprichter(s) 1 · Aandelen: 650" in text
        assert "Oprichter(s) 1 · Adres: Kerkstraat 12, Gent" in text and "Geattesteerd bedrag: EUR 412.500,00" in text
        assert "Oprichter(s) 2 · Naam: Anna Peeters" in text and "Oprichter(s) 3 · Naam: Tom Janssens" in text and "Oprichter(s) 3 · Aandelen: 50" in text
        assert "Oprichter(s): " not in text  # the list's own line is its entries
        assert "Zetel: Sint-Jansvest 18, Gent" in text  # the clerk's correction, confirmed by the manager


@needs_db
def test_a_list_the_documents_name_nothing_of_is_asked_about_and_an_answer_becomes_its_first_entry(runs):
    """The read's "none" for the list is one open fact; a person's answer in a form lands on the first entry's
    values and settles the list (``_settle_lists``)."""
    nobody = json.loads(FORMATION_ANSWER)
    nobody["founders"] = []
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text=json.dumps(nobody)))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        cid = c.post("/v1/cases", json={**NEW, "type": "company-formation"}, headers=alice).json()["id"]
        rid = c.post(f"/v1/cases/{cid}/playbooks/company-formation/runs", json={"language": "en"}, headers=alice).json()["id"]
        run = through_the_requests(c, cid, rid, alice, docs, kind="In kind")
        by = {f["id"]: f for f in run["facts"]}
        assert by["founders"]["found"] is False and not any(k.startswith("founders[") for k in by)
        # in kind: the bank certificate is neither asked for nor read, its facts don't exist in the run, and the thread says why
        assert run["steps"]["bank"]["because"] == "contribution_kind != in_kind; in_kind" and run["steps"]["bank_read"]["status"] == "skipped"
        assert "bank_certificate" not in by and "certified_amount" not in by
        assert "bank_certificate" not in [t for t in run["turns"] if t["step_id"] == "missing"][0]["meta"]["facts"]
        assert run["steps"]["reports"]["status"] == "active" or run["steps"]["reports"]["status"] == "done"
        assert "auditor" in by  # the reports' read ran (the stub answers null for what it doesn't know)
        assert "bank_certifies_the_contribution" not in run["checks"] and "contributions_add_up" not in run["checks"]
        asked = [t for t in run["turns"] if t["step_id"] == "missing"][0]
        assert "founders" in asked["meta"]["facts"]
        # the form answers for the first founder; the list's "none" is settled
        r = c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {"founders[1].name": "Filip Tack", "founders[1].shares": "1000"}}, headers=alice)
        assert r.status_code == 200 and r.json()["step"] == "confirm"
        rows = c.app.state.runs.get().fact_rows(uuid.UUID(rid))
        assert [(r_["fact_id"], r_["status"]) for r_ in rows if r_["fact_id"].startswith("founders")] == [
            ("founders", "superseded"), ("founders[1].name", "proposed"), ("founders[1].shares", "proposed")]
        r = c.put(RUN.format(cid=cid, rid=rid) + "/facts", json={"facts": [{"id": "founders[1].name", "confirmed": "Filip Tack"}]}, headers=alice)
        assert r.status_code == 200 and r.json()["status"] == "done"
        _, text = docs.stored_text
        assert "Founder(s) 1 · Name: Filip Tack" in text and "Founder(s): " not in text


@needs_db
def test_a_run_keeps_the_manifest_it_started_under(office):
    """A run is pinned to its manifest (docs/design/playbooks.md, "The data model"): what it shows, asks and
    produces comes from the record it made at the start, whatever is installed later. Simulated by editing
    the record in the database as an upgrade would change the installed file."""
    c, kc, _, docs, _ = office
    alice = as_user(kc, ALICE)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice).json()["id"]
    run = c.get(RUN.format(cid=cid, rid=rid), headers=alice).json()
    assert run["playbook"]["version"] == "1.7" and run["playbook"]["text"]["nl"]["labels"]["price"] == "Prijs"
    assert run["playbook"]["lists"]["conditions"] == ["condition", "term"] and run["playbook"]["kinds"]["price"] == "amount"
    # "the next release" renames a label and bumps the version; the run doesn't follow it
    store = c.app.state.runs.get()
    record = store._execute("SELECT manifest FROM playbook_runs WHERE id = %s", (uuid.UUID(rid),)).fetchone()[0]
    record["version"], record["text"]["nl"]["labels"]["price"] = "0.9", "Koopsom"
    store._execute("UPDATE playbook_runs SET manifest = %s WHERE id = %s", (json.dumps(record), uuid.UUID(rid)))
    run = c.get(RUN.format(cid=cid, rid=rid), headers=alice).json()
    assert run["playbook"]["version"] == "0.9" and run["playbook"]["text"]["nl"]["labels"]["price"] == "Koopsom"
    assert run["playbook_version"] == "1.7"  # what was recorded at the start stays the run's version
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    deliver(c, RUN.format(cid=cid, rid=rid), alice)
    run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
    c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "missing", "facts": {}}, headers=alice)
    r = c.put(RUN.format(cid=cid, rid=rid) + "/facts", json={"facts": [{"id": "price", "confirmed": "EUR 412.000,00"}]}, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "done"
    _, text = docs.stored_text
    assert "Koopsom: EUR 412.000,00" in text and "Prijs:" not in text  # the summary uses the run's own words


CARE_ANSWER = json.dumps({
    "principal": {"value": "Godelieve Van Testergem", "sources": [1]}, "start": {"value": "on_incapacity", "sources": [1]},
    "gift_power": {"value": "yes", "sources": [1]}, "incapacity_proof": {"value": "twee medische attesten", "sources": [1]},
    "gift_terms": {"value": "aan de kleinkinderen", "sources": [1]},
})


@needs_db
def test_reads_that_follow_each_other_run_one_after_the_other(runs):
    """The pod round of aebf5bc's playbook runs: the care mandate's branches are reads with no one in between (the
    incapacity, then the gifts), and the second one failed the run ("a second read step is not supported yet").
    Each now runs after the other in the same task, each asking for its own facts."""
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    captured: list = []
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport(captured, text=CARE_ANSWER))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        cid = c.post("/v1/cases", json={**NEW, "type": "care-mandate", "name": "Zorgvolmacht"}, headers=alice).json()["id"]
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        rid = c.post(f"/v1/cases/{cid}/playbooks/care-mandate/runs", json={"language": "nl"}, headers=alice).json()["id"]
        run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
        assert run["step"] == "choices"
        c.post(RUN.format(cid=cid, rid=rid) + "/answer", json={"step_id": "choices", "documents": [DOC]}, headers=alice)
        run = wait_for(c, RUN.format(cid=cid, rid=rid), alice, "waiting")
        assert run["status"] == "waiting" and run["step"] in ("missing", "confirm"), (run["status"], run["step"], run.get("error"))
        assert all(run["steps"][s]["status"] == "done" for s in ("choices_read", "incapacity_read", "gift_read")), run["steps"]
        shapes = [sorted(b["response_format"]["json_schema"]["schema"]["properties"]) for b in captured if "response_format" in b]
        assert shapes == [["gift_power", "principal", "start"], ["incapacity_proof"], ["gift_terms"]]
        by = {f["id"]: f["value"] for f in run["facts"]}
        assert by["incapacity_proof"] == "twee medische attesten" and by["gift_terms"] == "aan de kleinkinderen"


@needs_db
def test_a_choice_in_words_that_are_none_of_its_options_is_asked_again_not_dropped(runs):
    """The GPU round's playbook runs (5 November): the care mandate's pay, placed in words that were none of its
    options, was dropped without a word and the fact stayed empty. Now it is "couldn't be placed", asked again;
    the options go with the mapping's prompt."""
    import json as _json
    kc, cases, docs = FakeKeycloak(), FakeCases(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    replies: list[str] = []
    prompts: list[str] = []
    reading = llm_transport([], text=FORMATION_ANSWER).handle_request

    def handler(request: httpx.Request) -> httpx.Response:
        content = _json.loads(request.content)["messages"][-1]["content"] if request.url.path.endswith("/chat/completions") else ""
        if "answered in their own words" in content:
            prompts.append(content)
            return streamed(replies.pop(0))
        return reading(request)

    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(handler))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases,
                     runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    with TestClient(app) as c:
        alice = as_user(kc, ALICE)
        cid = c.post("/v1/cases", json={**NEW, "type": "company-formation", "name": "Oprichting"}, headers=alice).json()["id"]
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        rid = c.post(f"/v1/cases/{cid}/playbooks/company-formation/runs", json={"language": "nl"}, headers=alice).json()["id"]
        url = RUN.format(cid=cid, rid=rid)
        for step in ("identity", "plan"):
            wait_for(c, url, alice, "waiting")
            c.post(url + "/answer", json={"step_id": step, "documents": [DOC]}, headers=alice)
        run = wait_for(c, url, alice, "waiting")
        assert run["step"] == "kind_known"
        replies.append("contribution_kind: met een bestelwagen")  # placed, but none of the options
        run = c.post(url + "/say", json={"text": "Ze brengen een bestelwagen in."}, headers=alice).json()
        assert run["step"] == "kind_known" and run["turns"][-1]["meta"]["kind"] == "unplaced"
        assert "contribution_kind: Contribution" not in prompts[0] and "(a choice; options: cash = In geld" in prompts[0], prompts[0]
        replies.append("contribution_kind: cash")
        run = c.post(url + "/say", json={"text": "Enkel in geld."}, headers=alice).json()
        assert run["step"] == "bank" and {f["id"]: f["value"] for f in run["facts"]}["contribution_kind"] == "cash"


# ------------------------------------------------------------------ a document that comes later (decision of 10 November 2026)

def _late_app(runs, replies: list[str]):
    """An app whose model answers with the last of ``replies`` (a test changes it between reads)."""
    kc, cases, history, docs = FakeKeycloak(), FakeCases(), FakeConversations(), FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))

    def handler(request: httpx.Request) -> httpx.Response:
        return llm_transport([], text=replies[-1]).handler(request)
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=httpx.MockTransport(handler))
    app = create_app(llm, documents=docs, load_documents=False, auth=auth, conversations=history, cases=cases, runs=runs,
                     case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory())
    return app, kc, docs


def _to_done(c, url, who):
    """Walk a run to its end: "not known yet" at the ask, the values as they stand at the checkpoint."""
    for _ in range(20):
        run = wait_for(c, url, who, "waiting") if c.get(url, headers=who).json()["status"] == "reading" else c.get(url, headers=who).json()
        if run["status"] == "done":
            return run
        kind = {s["id"]: s["kind"] for s in run["playbook"]["steps"]}[run["step"]]
        if kind == "ask":
            c.post(url + "/answer", json={"step_id": run["step"], "facts": {}}, headers=who)
        elif kind == "checkpoint":
            c.put(url + "/facts", json={"facts": [{"id": f["id"], "confirmed": f["confirmed"] if f["confirmed"] is not None else f["value"]}
                                                  for f in run["facts"]]}, headers=who)
        else:
            raise AssertionError(f"waiting on a {kind}")
    raise AssertionError("never done")


@needs_db
def test_a_document_that_comes_later_is_read_for_its_facts_and_a_confirmed_run_is_reopened(runs):
    """The title deed comes after the run was confirmed: only the read aimed at it runs again, the empty title fact
    takes its reading, the run goes back to its checkpoint with the summary out of date, and confirmed again it makes
    a new summary. A later agreement that reads the price differently doesn't replace the confirmed price: both are
    shown until a person chooses."""
    from test_facts import leaf
    replies = [TABLE]
    app, kc, docs = _late_app(runs, replies)
    with TestClient(app) as c:
        cid, alice, bob = a_case_with_a_contributor(c, kc)
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"language": "nl"}, headers=alice).json()["id"]
        url = RUN.format(cid=cid, rid=rid)
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        deliver(c, url, alice)
        first = _to_done(c, url, alice)
        by = {f["id"]: f for f in first["facts"]}
        assert first["result_document_id"] and not first["out_of_date"] and by["title"]["confirmed"] == ""
        # not yet: a request the run hasn't reached, or one that isn't named
        assert c.post(url + "/documents", json={"step_id": "agreement_read", "documents": [DOC]}, headers=alice).status_code == 404
        assert c.post(url + "/documents", json={"step_id": "title_deed", "documents": [DOC]}, headers=bob).status_code == 403
        # the title deed, a week later
        late = "22222222-2222-2222-2222-222222222222"
        docs.docs[late] = (Scope.case(uuid.UUID(cid)), "uploaded")
        replies.append(json.dumps({**ANSWER, "title": leaf("Akte van 3 maart 1998, notaris Peeters", 1),
                                   "price": leaf("EUR 999.999,00", 1)}, ensure_ascii=False))
        r = c.post(url + "/documents", json={"step_id": "title_deed", "documents": [late]}, headers=alice)
        assert r.status_code == 200 and r.json()["status"] == "reading" and r.json()["out_of_date"] is True
        run = wait_for(c, url, alice, "waiting")
        assert run["step"] == "confirm" and run["steps"]["title_read"]["status"] == "done"
        assert run["steps"]["agreement_read"]["status"] == "done" and run["steps"]["certificates_read"]["status"] == "done"
        by = {f["id"]: f for f in run["facts"]}
        assert by["title"]["value"] == "Akte van 3 maart 1998, notaris Peeters"  # was empty: it takes the reading
        assert by["price"]["confirmed"] == "EUR 412.500,00" and by["price"]["alternative"] is None  # not read again: not its read
        said = [t["meta"] for t in run["turns"] if t["meta"].get("kind") == "late_documents"]
        assert said == [{"kind": "late_documents", "step": "title_deed", "documents": ["akte.pdf"], "reads": ["title_read"], "reopened": True}]
        done = _to_done(c, url, alice)
        assert done["status"] == "done" and not done["out_of_date"] and done["result_document_id"] != first["result_document_id"]
        assert {f["id"]: f for f in done["facts"]}["title"]["confirmed"] == "Akte van 3 maart 1998, notaris Peeters"
        # a second agreement that reads the price differently: the confirmed price stands, the new one waits beside it
        third = "33333333-3333-3333-3333-333333333333"
        docs.docs[third] = (Scope.case(uuid.UUID(cid)), "uploaded")
        c.post(url + "/documents", json={"step_id": "agreement", "documents": [third]}, headers=alice)
        run = wait_for(c, url, alice, "waiting")
        price = {f["id"]: f for f in run["facts"]}["price"]
        assert price["confirmed"] == "EUR 412.500,00" and price["alternative"]["value"] == "EUR 999.999,00"
        assert [t["meta"] for t in run["turns"] if t["meta"].get("kind") == "checkpoint"][-1]["differ"] == 1
        # the person chooses the new one: the alternative is settled, the choice confirmed
        facts = [{"id": f["id"], "confirmed": f["confirmed"] if f["confirmed"] is not None else f["value"]} for f in run["facts"]]
        facts = [{**f, "confirmed": "EUR 999.999,00"} if f["id"] == "price" else f for f in facts]
        c.put(url + "/facts", json={"facts": facts}, headers=alice)
        end = wait_for(c, url, alice, "done")
        price = {f["id"]: f for f in end["facts"]}["price"]
        assert price["confirmed"] == "EUR 999.999,00" and price["alternative"] is None


def test_every_kind_of_playbook_turn_the_server_writes_is_listed_for_the_screen():
    """The kinds in turn_kinds.json are what the server writes and what the chat UI words (its test reads the same file):
    a kind written but not listed, or listed but never written, fails (decision of 12 November 2026)."""
    import ast
    from pathlib import Path

    from suveryn_api_gateway.playbooks import TURN_KINDS
    src = Path(__file__).resolve().parents[1] / "src" / "suveryn_api_gateway"
    written = set()
    for path in (src / "playbook_runtime.py", src / "routes" / "playbooks.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        says = ("say", "_say")  # called, or handed to run_in_threadpool
        nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and (getattr(n.func, "attr", None) in says
                                                                           or any(getattr(a, "attr", None) in says for a in n.args))]
        nodes += [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.endswith("_turn")]
        for node in nodes:
            for d in ast.walk(node):
                if isinstance(d, ast.Dict):
                    for k, v in zip(d.keys, d.values):
                        if isinstance(k, ast.Constant) and k.value == "kind" and isinstance(v, ast.Constant):
                            written.add(v.value)
    assert written == set(TURN_KINDS)


def test_a_run_says_why_it_failed_as_a_code_of_the_registry_with_its_kind():
    # stored as code and parameters (the decision of 12 November, rule 6), sent as {kind, code, params}
    from suveryn_harness.messages import message
    from suveryn_harness.messages import stored as _failure
    assert _failure(json.dumps(message("model.unavailable"))) == {"kind": "unavailable", "code": "model.unavailable", "params": {}}
    assert _failure(json.dumps(message("system.internal", ref="7F3K-92QD")))["params"] == {"ref": "7F3K-92QD"}
    assert _failure(json.dumps(message("run.no_document")))["kind"] == "refused"
    assert _failure(None) is None
    # a run that failed before failures were codes stored a bare word: it failed, and the page says so by its kind
    assert _failure("model_unavailable") == {"kind": "internal", "code": "system.internal", "params": {}}


@needs_db
def test_every_answer_of_playbooks_is_what_the_description_says(office, runs):
    """The chat UI's code for playbooks is generated from the description (suveryn-tracker#247): each answer the
    operations give, the refusals too, is checked against it and kept for the chat UI's tests. A run is kept where it
    waits for a person, never while the model reads: that moment isn't the same every run."""
    import re

    from described import Checked
    from suveryn_api_gateway.ratelimit import RateLimits
    from test_cases import CARLA

    c, kc, _, docs, _ = office
    check, admin = Checked(c, "playbooks"), admin_headers(kc)
    cid, alice, bob = a_case_with_a_contributor(c, kc, "contributor")
    carla = as_user(kc, CARLA)
    c.put(f"/v1/cases/{cid}/members/{CARLA}", json={"role": "reader"}, headers=alice)
    WHEN, GONE, LATE = "2026-11-23T09:00:00Z", "00000000-0000-4000-8000-00000000dead", "22222222-2222-2222-2222-222222222222"
    ids: dict[str, str] = {DOC: "11111111-1111-1111-1111-111111111111", LATE: LATE, GONE: GONE}
    an_id = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

    def fixed(value: str) -> str:  # this run's ids, in the order they are first seen
        return ids.setdefault(value, f"00000000-0000-4000-8000-{len(ids):012x}") if an_id.match(value) else value

    def same(body):  # this run's ids, moments and counters, wherever they are in an answer
        if isinstance(body, list):
            return [same(item) for item in body]
        if not isinstance(body, dict):
            return fixed(body) if isinstance(body, str) else body
        out = {}
        for key, value in body.items():
            if (key == "at" or key.endswith("_at")) and isinstance(value, str):
                out[fixed(key)] = WHEN
            elif key == "facts_seq":
                out[key] = 1  # the database's counter over every run's facts
            elif key == "turns" and isinstance(value, list):
                out[key] = [{**same(t), "seq": i} for i, t in enumerate(value)]
            else:
                out[fixed(key)] = same(value)
        return out

    def tidy(body):  # in place, as ``Kept`` asks
        new = same(body)
        body.clear() if isinstance(body, dict) else body.__delitem__(slice(None))
        body.update(new) if isinstance(body, dict) else body.extend(new)

    every = "/v1/cases/{case_id}/playbooks"
    office_list, one, active, runs_, run, start = "/v1/admin/playbooks", "/v1/admin/playbooks/{playbook}", "/v1/playbooks/runs/active", \
        every + "/runs", every + "/runs/{run_id}", every + "/{playbook}/runs"
    in_case = lambda rest="", case=cid: f"/v1/cases/{case}/playbooks{rest}"  # noqa: E731
    acts = [("POST", "/answer", {"json": {"step_id": "agreement"}}), ("POST", "/say", {"json": {"text": "x"}}),
            ("POST", "/documents", {"json": {"step_id": "title_deed", "documents": [DOC]}}), ("PUT", "/facts", {"json": {"facts": [{"id": "price", "confirmed": "1"}]}}),
            ("PUT", "/facts/{fact_id}", {"json": {"value": "1"}}), ("POST", "/pause", {}), ("POST", "/resume", {}), ("POST", "/stop", {}),
            ("POST", "/cancel", {"json": {}})]
    of_case = [("GET", every, "", {}), ("GET", runs_, "/runs", {}), ("GET", run, f"/runs/{GONE}", {}), ("POST", start, "/deed-intake/runs", {"json": {}}),
               *[(m, run + rest, f"/runs/{GONE}{rest}".replace("{fact_id}", "price"), sent) for m, rest, sent in acts]]
    for method, path, at, sent in [("GET", office_list, None, {}), ("PUT", one, "/v1/admin/playbooks/deed-intake", {"json": {"active": True}}), ("GET", active, None, {})]:
        assert check(method, path, 401, at, **sent).json()["code"] == "auth.signed_out"
    for method, path, rest, sent in of_case:
        assert check(method, path, 401, in_case(rest), **sent).json()["code"] == "auth.signed_out"
        assert check(method, path, 422, in_case(rest, "not-an-id"), headers=alice, **sent).json()["code"] == "request.invalid"
        assert check(method, path, 404, in_case(rest, GONE), headers=alice, **sent).json()["code"] == "case.not_found"
        if "{run_id}" in path:  # a run that doesn't exist, and what isn't a run id at all
            r = check(method, path, 404, in_case(rest), "no_such_run" if method == "GET" else None, headers=alice, **sent)
            assert r.json()["code"] == "request.not_found"
            assert check(method, path, 422, in_case(rest.replace(GONE, "not-an-id")), headers=alice, **sent).json()["code"] == "request.invalid"

    # the administrator's list, and a playbook switched off and on
    assert check("GET", office_list, 403, headers=alice).json()["code"] == "request.forbidden"
    assert len(check("GET", office_list, 200, headers=admin).json()) == 3
    assert check("PUT", one, 403, "/v1/admin/playbooks/deed-intake", json={"active": False}, headers=alice).json()["code"] == "request.forbidden"
    assert check("PUT", one, 404, "/v1/admin/playbooks/nope", json={"active": False}, headers=admin).json()["code"] == "request.not_found"
    assert "errors" in check("PUT", one, 422, "/v1/admin/playbooks/deed-intake", json={}, headers=admin).json()
    assert check("PUT", one, 200, "/v1/admin/playbooks/deed-intake", json={"active": False}, headers=admin).json()["active"] is False
    assert check("GET", every, 200, in_case(), headers=alice).json() == []
    assert check("POST", start, 404, in_case("/deed-intake/runs"), json={}, headers=alice).json()["code"] == "request.not_found"
    check("PUT", one, 200, "/v1/admin/playbooks/deed-intake", json={"active": True}, headers=admin)
    assert [p["slug"] for p in check("GET", every, 200, in_case(), "fitting", headers=bob).json()] == ["deed-intake"]

    # a run starts and waits for the agreement
    assert check("POST", start, 403, in_case("/deed-intake/runs"), json={}, headers=carla).json()["code"] == "case.not_allowed"
    assert "errors" in check("POST", start, 422, in_case("/deed-intake/runs"), json={"language": "Dutch"}, headers=alice).json()
    started = check("POST", start, 202, in_case("/deed-intake/runs"), "started", tidy=tidy, json={"language": "nl"}, headers=alice).json()
    rid = started["id"]
    of_run = lambda rest="": in_case(f"/runs/{rid}{rest}")  # noqa: E731
    r = check("POST", start, 409, in_case("/deed-intake/runs"), "already_going", tidy=tidy, json={}, headers=alice)
    assert (r.json()["code"], r.json()["params"]["run"]) == ("run.already_going", rid)
    assert check("GET", active, 200, keep="active", tidy=tidy, headers=bob).json()[cid]["step_kind"] == "request"
    assert [x["id"] for x in check("GET", runs_, 200, in_case("/runs"), "runs", tidy=tidy, headers=bob).json()] == [rid]
    assert check("POST", run + "/pause", 403, of_run("/pause"), headers=carla).json()["code"] == "case.not_allowed"
    assert check("POST", run + "/pause", 200, of_run("/pause"), headers=bob).json()["paused_by"] == "bob.test"
    for method, rest, sent in [("POST", "/pause", {}), ("POST", "/answer", {"json": {"step_id": "agreement"}}), ("POST", "/say", {"json": {"text": "x"}})]:
        r = check(method, run + rest, 409, of_run(rest), "is_paused" if rest == "/pause" else None, headers=alice, **sent)
        assert r.json()["code"] == "run.paused"
    assert check("POST", run + "/resume", 403, of_run("/resume"), headers=carla).json()["code"] == "case.not_allowed"
    assert check("POST", run + "/resume", 200, of_run("/resume"), headers=alice).json()["status"] == "waiting"
    assert check("POST", run + "/resume", 409, of_run("/resume"), headers=alice).json()["code"].startswith("run.")

    # the requests are answered, in words with the document and by saying there is none
    assert check("POST", run + "/answer", 403, of_run("/answer"), json={"step_id": "agreement"}, headers=carla).json()["code"] == "case.not_allowed"
    assert check("POST", run + "/answer", 422, of_run("/answer"), json={"step_id": "agreement", "none": True}, headers=alice).json()["code"] == "request.invalid"
    r = check("POST", run + "/answer", 409, of_run("/answer"), "moved_on", json={"step_id": "read"}, headers=alice)
    assert r.json()["code"] == "run.moved_on"
    assert check("POST", run + "/say", 403, of_run("/say"), json={"text": "x"}, headers=carla).json()["code"] == "case.not_allowed"
    assert "errors" in check("POST", run + "/say", 422, of_run("/say"), json={"documents": "all"}, headers=alice).json()
    assert check("POST", run + "/say", 404, of_run("/say"), json={"documents": [DOC]}, headers=alice).json()["code"].endswith("not_found")  # not in the case yet
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    said = check("POST", run + "/say", 200, of_run("/say"), json={"text": "Hier is het compromis.", "documents": [DOC]}, headers=alice).json()
    assert (said["status"], said["step"]) == ("waiting", "title_deed")
    for step in ("title_deed", "certificates"):
        check("POST", run + "/answer", 200, of_run("/answer"), json={"step_id": step, "none": True}, headers=alice)
    wait_for(c, of_run(), alice, "waiting")
    asking = check("GET", run, 200, of_run(), "asking", tidy=tidy, headers=bob).json()
    assert asking["step"] == "missing" and {f["id"]: f for f in asking["facts"]}["price"]["value"] == "EUR 412.500,00"

    # the ask is answered; at the checkpoint a value is adjusted, and confirmed from the screen that saw it
    r = check("POST", run + "/answer", 200, of_run("/answer"), json={"step_id": "missing", "facts": {"cadastral": "Gent 5e afd., sectie B, nr. 123"}}, headers=alice)
    assert r.json()["step"] == "confirm" and r.json()["checks"]["a_seller"]["status"] == "holds"
    seen_before = r.json()["facts_seq"]
    assert check("PUT", run + "/facts/{fact_id}", 403, of_run("/facts/price"), json={"value": "1"}, headers=carla).json()["code"] == "case.not_allowed"
    assert "errors" in check("PUT", run + "/facts/{fact_id}", 422, of_run("/facts/price"), json={"value": ""}, headers=bob).json()
    assert check("PUT", run + "/facts/{fact_id}", 404, of_run("/facts/nope"), json={"value": "1"}, headers=bob).json()["code"].endswith("not_found")
    adjusted = check("PUT", run + "/facts/{fact_id}", 200, of_run("/facts/price"), json={"value": "EUR 415.000,00"}, headers=bob).json()
    assert {f["id"]: f for f in adjusted["facts"]}["price"]["by"] == "bob.test"
    as_shown = [{"id": f["id"], "confirmed": f["value"]} for f in adjusted["facts"]]
    assert check("PUT", run + "/facts", 403, of_run("/facts"), json={"facts": as_shown}, headers=carla).json()["code"] == "case.not_allowed"
    assert check("PUT", run + "/facts", 422, of_run("/facts"), json={"facts": [{"id": "x", "confirmed": ""}]}, headers=alice).json()["code"] == "request.invalid"
    r = check("PUT", run + "/facts", 409, of_run("/facts"), "facts_changed", json={"facts": as_shown, "seen": seen_before}, headers=alice)
    assert r.json()["code"] == "run.facts_changed"
    done = check("PUT", run + "/facts", 200, of_run("/facts"), "done", tidy=tidy, json={"facts": as_shown, "seen": adjusted["facts_seq"]}, headers=alice).json()
    assert done["status"] == "done" and done["result_document_id"] and done["confirmed_by"] == "notaris.test"

    # a document that comes later reopens the run at its checkpoint
    late = {"step_id": "title_deed", "documents": [LATE]}
    assert check("POST", run + "/documents", 403, of_run("/documents"), json=late, headers=carla).json()["code"] == "case.not_allowed"
    assert "errors" in check("POST", run + "/documents", 422, of_run("/documents"), json={"step_id": "title_deed"}, headers=alice).json()
    assert check("POST", run + "/documents", 404, of_run("/documents"), json=late, headers=alice).json()["code"].endswith("not_found")  # not in the case
    docs.docs[LATE] = (Scope.case(uuid.UUID(cid)), "uploaded")
    assert check("POST", run + "/documents", 200, of_run("/documents"), json=late, headers=alice).json()["out_of_date"] is True
    wait_for(c, of_run(), alice, "waiting")
    reopened = check("GET", run, 200, of_run(), headers=alice).json()
    assert reopened["step"] == "confirm" and reopened["turns"][-2]["meta"]["kind"] == "late_documents"

    # it is stopped by who started it or manages the case; ended, nothing more is done in it
    assert check("POST", run + "/stop", 403, of_run("/stop"), "starter_or_manager_only", headers=bob).json()["code"] == "run.starter_or_manager_only"
    assert check("POST", run + "/cancel", 403, of_run("/cancel"), json={}, headers=bob).json()["code"] == "run.starter_or_manager_only"
    assert "errors" in check("POST", run + "/cancel", 422, of_run("/cancel"), json={"reason": "x" * 501}, headers=alice).json()
    assert check("POST", run + "/stop", 200, of_run("/stop"), headers=alice).json()["ended_by"] == "notaris.test"
    for method, rest, sent in acts:
        r = check(method, run + rest, 409, of_run(rest).replace("{fact_id}", "price"), "ended" if rest == "/stop" else None, headers=alice, **sent)
        assert r.json()["code"] == "run.ended", (rest, r.json()["code"])
    again = check("POST", start, 202, in_case("/deed-intake/runs"), json={}, headers=alice).json()["id"]
    r = check("POST", run + "/cancel", 200, in_case(f"/runs/{again}/cancel"), "cancelled", tidy=tidy, json={"reason": "wrong file"}, headers=alice)
    assert (r.json()["status"], r.json()["ended_reason"]) == ("cancelled", "wrong file")

    # the office's limit on asking the model holds for starting a run (an office of its own, with a limit of one)
    kc2, cases2 = FakeKeycloak(), FakeCases()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc2.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([], text=TABLE))
    limited = create_app(llm, documents=FakeDocuments(owner=ALICE), load_documents=False, auth=auth, conversations=FakeConversations(), cases=cases2,
                         runs=runs, case_settings=CaseSettings(default_access="members", keep="6m"), directory=FakeDirectory(), rate_limits=RateLimits(chat=1))
    with TestClient(limited) as c2:
        check2, alice2 = Checked(c2, "playbooks"), as_user(kc2, ALICE)
        check2.kept = check.kept
        first, second = (c2.post("/v1/cases", json={**NEW, "reference": f"2026/{i}"}, headers=alice2).json()["id"] for i in (1, 2))
        check2("POST", start, 202, in_case("/deed-intake/runs", first), json={}, headers=alice2)
        r = check2("POST", start, 429, in_case("/deed-intake/runs", second), "too_many", headers=alice2, json={})
        assert r.json()["kind"] == "refused"
        check.seen |= check2.seen
    check.kept.check()
    # not seen here, each for a reason: what nobody planned for (500); sign-in, the runs' store or the model down
    # (503: test_auth.py and the tests above); the same limit where an answer makes the model read again, and the
    # limit on runs reading at once (429: test_only_so_many_runs_read_at_once); sign-in turned off for another
    # machine, for what anyone signed in may ask (403)
    for method, path, status in check.not_seen():
        assert status in (500, 503) or (status == 429 and path != start) or (status == 403 and (method, path) in {
            ("GET", active), ("GET", every), ("GET", runs_), ("GET", run)}), (method, path, status)
    assert {s for _, _, s in check.seen} == {200, 202, 401, 403, 404, 409, 422, 429}


def test_every_turn_a_run_writes_is_described():
    """What a turn of a run's thread means is described (suveryn-tracker#250): every member the gateway writes into one
    is one ``TurnMeta`` has. Read from the code: the turns the playbook says (a dict with a ``kind``) and the ones a
    person's words come with (``meta``)."""
    import ast
    import pathlib

    from suveryn_api_gateway.playbooks import TURN_KINDS, TurnMeta

    package = pathlib.Path(__import__("suveryn_api_gateway").__file__).parent
    written = set()
    for module in (package / "playbook_runtime.py", package / "playbooks.py", package / "routes" / "playbooks.py"):
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Dict):
                keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
                kind = next((v.value for k, v in zip(node.keys, node.values) if isinstance(k, ast.Constant) and k.value == "kind"
                             and isinstance(v, ast.Constant)), None)
                if kind in TURN_KINDS:
                    written |= keys
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "say" or isinstance(node, ast.Call) and len(node.args) == 7 and \
                    isinstance(node.args[0], ast.Attribute) and node.args[0].attr == "say":
                for part in ast.walk(node):
                    if isinstance(part, ast.Dict):
                        written |= {k.value for k in part.keys if isinstance(k, ast.Constant)}
            if isinstance(node, ast.Subscript) and getattr(node.value, "id", "") == "meta" and isinstance(node.slice, ast.Constant):
                written.add(node.slice.value)
    assert {"kind", "facts", "found", "answers", "attachments", "late", "unknown", "case_documents"} <= written
    attached = {"documentId", "filename"}  # an attachment's own members, in a list under ``attachments``
    assert written - attached <= set(TurnMeta.model_fields), sorted(written - attached - set(TurnMeta.model_fields))


def test_a_turn_or_a_worked_out_value_kept_in_another_shape_is_still_read():
    """A run whose thread or facts were kept in a shape from before is opened all the same: what doesn't fit is left
    out, the turn and the value stand."""
    from suveryn_api_gateway.playbooks import TurnMeta
    from suveryn_harness.facts import ShareComputed, TermComputed, computed_or_none

    assert TurnMeta.kept({"kind": "ask", "facts": ["price"], "found": 3, "total": 4}).model_dump() == {"kind": "ask", "facts": ["price"], "found": 3, "total": 4}
    assert TurnMeta.kept({"kind": "a kind of before", "found": "three", "step": "read"}).model_dump() == {"step": "read"}
    assert TurnMeta.kept(None).model_dump() == {}
    term = {"written": "binnen vier maanden", "from": "agreement_date", "base": "2026-10-03", "date": "2027-02-03", "amount": 4,
            "unit": "month", "direction": "after"}
    assert isinstance(computed_or_none(term), TermComputed) and computed_or_none(term).model_dump()["from"] == "agreement_date"
    share = {"written": "tien procent", "from": "price", "kind": "share", "percent": "10", "of": "412500.00", "amount": "41250.00"}
    assert isinstance(computed_or_none(share), ShareComputed)
    assert computed_or_none({"written": "binnen vier maanden"}) is None and computed_or_none(None) is None
