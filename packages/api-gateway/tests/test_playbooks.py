"""Playbook runs (suveryn-tracker#51): deed intake read from a case's documents, checked at the
checkpoint, stored as a document with origin ``playbook``. Design: docs/design/playbooks.md."""

import os
import time
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.cases import CaseSettings
from suveryn_api_gateway.playbooks import RunStore, read_facts, summary_text
from suveryn_engine import (
    ChatResponse,
    Citation,
    LlamaServerClient,
    LLMSettings,
    SourceRef,
)
from suveryn_playbooks import DEED_INTAKE
from suveryn_rag.store import Scope
from test_auth import SETTINGS, FakeKeycloak
from test_cases import ALICE, BOB, NEW, FakeCases, FakeDirectory
from test_conversations import FakeConversations, as_user
from test_documents import DOC, FakeDocuments, llm_transport

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
    from suveryn_chat.calc import unverified_figures
    from suveryn_chat.support import citation_issues
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


def test_summary_text_uses_the_confirmed_values_and_the_language():
    from suveryn_api_gateway.playbooks import Run
    facts = read_facts(DEED_INTAKE, response(), {DOC: "compromis.pdf"})
    for f in facts:
        f.confirmed = "EUR 412.000,00" if f.id == "price" else f.value
    run = Run(id=str(uuid.uuid4()), case_id=str(uuid.uuid4()), playbook_id=DEED_INTAKE.id, playbook_version="1.0",
              status="confirmed", documents=[DOC], started_by=ALICE, started_at="2026-10-17T10:00:00Z", facts=facts)
    text = summary_text(DEED_INTAKE, "2026/0417", run, "nl")
    assert text.startswith("Intake akte 2026/0417\n\nplaybook/be-notary/deed-intake 1.0")
    assert "Prijs: EUR 412.000,00 (compromis.pdf p. 1)" in text and "Kadastrale gegevens: —" in text


# ------------------------------------------------------------------ through the app (needs PostgreSQL for the runs)

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")


@pytest.fixture
def runs():
    s = RunStore(URL)
    yield s
    s._execute("DELETE FROM playbook_runs WHERE started_by IN (%s, %s, %s)", (ALICE, BOB, "notaris.test"))
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


def wait_for(c, url, headers, status, tries=50):
    for _ in range(tries):
        run = c.get(url, headers=headers).json()
        if run["status"] == status:
            return run
        time.sleep(0.05)
    raise AssertionError(f"run never reached {status}: {run['status']}")


@needs_db
def test_deed_intake_reads_the_case_checks_the_facts_and_stores_the_summary(office):
    c, kc, _, docs, captured = office
    alice, bob = as_user(kc, ALICE), as_user(kc, BOB)
    cid = c.post("/v1/cases", json=NEW, headers=alice).json()["id"]
    c.put(f"/v1/cases/{cid}/members/{BOB}", json={"role": "reader"}, headers=alice)
    docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
    docs.docs[str(uuid.uuid4())] = (Scope.case(uuid.UUID(cid)), "playbook")  # an earlier result: never read
    # which playbooks fit: a sale gets deed intake, entitled
    fits = c.get(f"/v1/cases/{cid}/playbooks", headers=bob).json()
    assert [(p["id"], p["entitled"], p["version"]) for p in fits] == [("playbook/be-notary/deed-intake", True, "1.0")]
    # a reader can't start; a contributor can, and the run reads only the uploaded document
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=bob).status_code == 403
    assert c.post(f"/v1/cases/{cid}/playbooks/estate-intake/runs", json={}, headers=alice).status_code == 404
    r = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice)
    assert r.status_code == 202 and r.json()["status"] == "reading" and r.json()["documents"] == [DOC]
    assert r.json()["playbook_id"] == "playbook/be-notary/deed-intake" and r.json()["playbook_version"] == "1.0"
    rid = r.json()["id"]
    run = wait_for(c, f"/v1/cases/{cid}/playbooks/runs/{rid}", bob, "checkpoint")
    assert "| sellers | | |" in captured[-1]["messages"][-1]["content"]  # the playbook's instructions went to the model
    by = {f["id"]: f for f in run["facts"]}
    assert by["price"]["value"] == "EUR 412.500,00" and by["price"]["citations"][0]["filename"] == "akte.pdf"
    assert run["model"] == "Qwen3.8-27B-UD-Q4_K_M.gguf" and by["cadastral"]["found"] is False
    assert [x["id"] for x in c.get(f"/v1/cases/{cid}/playbooks/runs", headers=bob).json()] == [rid]
    # the checkpoint: a reader can't confirm; the contributor corrects the price and confirms the rest
    confirm = {"facts": [{"id": "price", "confirmed": "EUR 412.000,00"}, {"id": "cadastral", "confirmed": "Gent 5e afd., sectie B, nr. 123"}],
               "language": "nl"}
    assert c.put(f"/v1/cases/{cid}/playbooks/runs/{rid}/facts", json=confirm, headers=bob).status_code == 403
    assert c.put(f"/v1/cases/{cid}/playbooks/runs/{rid}/facts", json={"facts": [{"id": "x", "confirmed": ""}]}, headers=alice).status_code == 422
    r = c.put(f"/v1/cases/{cid}/playbooks/runs/{rid}/facts", json=confirm, headers=alice)
    assert r.status_code == 200 and r.json()["status"] == "confirmed" and r.json()["confirmed_by"] == "notaris.test"
    by = {f["id"]: f for f in r.json()["facts"]}
    assert by["price"]["confirmed"] == "EUR 412.000,00" and by["price"]["value"] == "EUR 412.500,00"
    assert by["sellers"]["confirmed"] == "Jan Peeters en Marie Claes" and by["cadastral"]["confirmed"].startswith("Gent")
    # the summary is a document in the case with origin playbook, named after the playbook and the case
    name, text = docs.stored_text
    assert name == "Deed intake 2026/0417 (1.0).txt" and "Prijs: EUR 412.000,00" in text
    assert docs.docs[r.json()["result_document_id"]] == (Scope.case(uuid.UUID(cid)), "playbook")
    assert c.put(f"/v1/cases/{cid}/playbooks/runs/{rid}/facts", json=confirm, headers=alice).status_code == 409
    # the access log has both steps
    actions = [e["action"] for e in c.get(f"/v1/cases/{cid}/events", headers=alice).json()]
    assert "playbook_started" in actions and "playbook_confirmed" in actions
    # a document the run read is deleted: the run stays, marked out of date; a closed case starts nothing
    assert c.delete(f"/v1/documents/{DOC}?case={cid}", headers=alice).status_code == 204
    assert c.get(f"/v1/cases/{cid}/playbooks/runs/{rid}", headers=alice).json()["out_of_date"] is True
    c.post(f"/v1/cases/{cid}/close", headers=alice)
    assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 403


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
        assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={}, headers=alice).status_code == 404  # nothing to read
        docs.docs[DOC] = (Scope.case(uuid.UUID(cid)), "uploaded")
        rid = c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"document_ids": [DOC]}, headers=alice).json()["id"]
        run = wait_for(c, f"/v1/cases/{cid}/playbooks/runs/{rid}", alice, "failed")
        assert run["error"] == "unreadable_answer" and run["facts"] == []
        assert c.post(f"/v1/cases/{cid}/playbooks/deed-intake/runs", json={"document_ids": [str(uuid.uuid4())]}, headers=alice).status_code == 404


@needs_db
def test_store_deletes_runs_with_the_case(runs):
    cid = uuid.uuid4()
    run = runs.create(cid, DEED_INTAKE, [DOC], ALICE, None)
    assert runs.get(uuid.UUID(run.id), cid).status == "reading" and runs.get(uuid.UUID(run.id), uuid.uuid4()) is None
    assert runs.confirm(uuid.UUID(run.id), cid, {}, "alice") is None  # not at the checkpoint
    assert runs.delete_case(cid) == 1 and runs.list(cid) == []
