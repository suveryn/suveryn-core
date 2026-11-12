"""Every refusal and failure in one shape: Problem Details with a code (problems.py; the handbook's decision of 12
November 2026, *Messages are codes*)."""
import logging
import re
from pathlib import Path

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient
from suveryn_api_gateway import problems
from suveryn_api_gateway.app import create_app
from suveryn_api_gateway.auth import Authenticator
from suveryn_harness import LlamaServerClient, LLMSettings
from suveryn_harness.messages import CODES, Problem

SRC = Path(__file__).resolve().parents[1] / "src" / "suveryn_api_gateway"


def an_app():
    backend = httpx.MockTransport(lambda request: httpx.Response(404))
    app = create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=backend), load_documents=False,
                     auth=Authenticator.disabled())

    @app.get("/v1/test/problem")
    async def a_problem():
        raise Problem("upload.too_large", "The file is larger than 100 MB.", max_mb=100)

    @app.get("/v1/test/plain")
    async def a_plain_refusal():
        raise HTTPException(409, "This case is already closed.")

    @app.get("/v1/test/unplanned")
    async def unplanned():
        raise FileNotFoundError("/srv/suveryn/originals/Echtscheiding Peeters.pdf")

    @app.get("/v1/test/number/{n}")
    async def a_number(n: int):
        return n
    return app


def test_a_problem_is_answered_as_problem_details_with_its_code():
    with TestClient(an_app()) as c:
        r = c.get("/v1/test/problem")
    assert r.status_code == 413 and r.headers["content-type"] == "application/problem+json"
    assert r.json() == {"type": "urn:suveryn:problem:upload.too_large", "title": CODES["upload.too_large"].title, "status": 413,
                        "detail": "The file is larger than 100 MB.", "kind": "refused", "code": "upload.too_large",
                        "params": {"max_mb": 100}}


def test_a_refusal_without_a_code_of_its_own_gets_its_status_s_general_code():
    with TestClient(an_app()) as c:
        r = c.get("/v1/test/plain")
        assert (r.status_code, r.json()["code"], r.json()["kind"]) == (409, "request.conflict", "refused")
        assert r.json()["detail"] == "This case is already closed."  # English, for developers; the page words the code
        r = c.get("/v1/nothing/here")
        assert (r.status_code, r.json()["code"]) == (404, "request.not_found")
        r = c.get("/v1/test/number/twelve")
        assert (r.status_code, r.json()["code"]) == (422, "request.invalid")
        assert r.json()["errors"][0]["loc"] == ["path", "n"] and "input" not in r.json()["errors"][0]  # never the values sent
    assert set(problems.GENERAL.values()) <= set(CODES)


def test_anything_unplanned_gets_a_reference_and_the_log_holds_no_message(caplog):
    with caplog.at_level(logging.ERROR, logger="suveryn.gateway"), TestClient(an_app()) as c:
        r = c.get("/v1/test/unplanned")
    body = r.json()
    assert (r.status_code, body["code"], body["kind"]) == (500, "system.internal", "internal")
    ref = body["params"]["ref"]
    assert re.fullmatch(r"[2-9A-HJ-NP-Z]{4}-[2-9A-HJ-NP-Z]{4}", ref) and "Peeters" not in r.text
    logged = [m for m in caplog.messages if ref in m]
    # the reference, the kind of exception and where; never its message, which may quote a document or name a file
    assert len(logged) == 1 and "FileNotFoundError" in logged[0] and "unplanned" in logged[0] and "Peeters" not in caplog.text


# The refusals still written as plain English sentences, each to become a code of the registry area by area. This
# number may only go down: lower it in the PR that moves an area, and never raise it; new code raises a Problem.
PLAIN_REFUSALS = 138


def test_the_plain_refusals_only_go_down():
    count = sum(len(re.findall(r"\bHTTPException\(", p.read_text(encoding="utf-8"))) for p in SRC.rglob("*.py") if p.name != "problems.py")
    assert count == PLAIN_REFUSALS, (
        f"{count} plain refusals, the test says {PLAIN_REFUSALS}: a new refusal is a Problem with a code of messages.json; "
        "when an area moved to codes, lower PLAIN_REFUSALS to the new count")
    # and none written by hand as a JSON answer
    assert not [p.name for p in SRC.rglob("*.py") if re.search(r'JSONResponse\(\{"detail"', p.read_text(encoding="utf-8"))]
