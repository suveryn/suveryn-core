"""suveryn-tracker#3: a user only ever sees their own documents.

Two users sign in with real RS256 access tokens from the fake Keycloak in test_auth.py; the fake
document service fails the test if the gateway ever asks it to read another owner's document.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from suveryn_api_gateway.app import LOCAL_OWNER, create_app, owner_of
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_engine import LLMSettings, LlamaServerClient
from test_auth import SETTINGS, FakeKeycloak
from test_documents import DOC, FakeDocuments, FakeJob, llm_transport

ALICE, BOB = "user-a", "user-b"
ASK = {"messages": [{"role": "user", "content": "Wat is de koopprijs?"}], "document_ids": [DOC]}


@pytest.fixture
def setup():
    kc = FakeKeycloak()
    docs = FakeDocuments(owner=ALICE)
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, documents=docs, load_documents=False, auth=auth)) as c:
        yield c, kc, docs


def as_user(kc: FakeKeycloak, sub: str) -> dict:
    return {"Authorization": f"Bearer {kc.tokens(over={'sub': sub})['access_token']}"}


def test_list_shows_only_your_own_documents(setup):
    c, kc, _ = setup
    assert [d["id"] for d in c.get("/v1/documents", headers=as_user(kc, ALICE)).json()["documents"]] == [DOC]
    assert c.get("/v1/documents", headers=as_user(kc, BOB)).json()["documents"] == []


def test_another_users_document_is_unknown_for_chat_and_delete(setup):
    c, kc, docs = setup
    bob = as_user(kc, BOB)
    assert c.post("/v1/chat", json=ASK, headers=bob).status_code == 404
    assert c.post("/v1/chat", json={**ASK, "stream": True}, headers=bob).status_code == 404
    assert docs.seen == {}  # the passages were never read
    assert c.delete(f"/v1/documents/{DOC}", headers=bob).status_code == 404
    assert DOC in docs.docs  # still there
    assert c.post("/v1/chat", json=ASK, headers=as_user(kc, ALICE)).status_code == 200
    assert docs.seen["owner"] == ALICE


def test_upload_jobs_are_private(setup):
    c, kc, docs = setup
    job = FakeJob("akte.pdf", owner=ALICE)
    docs.jobs[job.id] = job
    assert c.get(f"/v1/documents/jobs/{job.id}", headers=as_user(kc, BOB)).status_code == 404
    assert c.get("/v1/documents", headers=as_user(kc, BOB)).json()["jobs"] == []
    assert c.get(f"/v1/documents/jobs/{job.id}", headers=as_user(kc, ALICE)).status_code == 200
    assert "owner" not in c.get(f"/v1/documents/jobs/{job.id}", headers=as_user(kc, ALICE)).json()


def test_owner_is_the_keycloak_user_id_or_local_when_sign_in_is_off():
    class Req:
        class state:  # noqa: N801
            user = None
    assert owner_of(Req) == LOCAL_OWNER
    Req.state.user = type("U", (), {"sub": ALICE})()
    assert owner_of(Req) == ALICE
