"""The lifecycle: what happens to a signed-in person when a service goes away and comes back (e2e/README.md).
Every finding here was first made by hand on a running appliance (handbook, testing/regression-gap-analysis.md):
the stores that never reconnected after PostgreSQL restarted, the sign-in page that sent people to a Keycloak whose
database was down, ``/health`` and Status that said sign-in worked while Keycloak was stopped, the model server
away. Each scenario stops a service with ``stack.py``, looks, starts it again, and checks the person is still signed
in and the stack works again, without a restart of the gateway.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect
from conftest import ask, health_part, service, sign_in, upload, wait_until
from stack import kc_token


@pytest.fixture
def restored():
    """Whatever a scenario stops is started again, also when it fails halfway."""
    stopped: list[str] = []
    yield stopped
    for name in reversed(stopped):
        service("start", name)
    wait_until(lambda: health_part("documents") == "ready" and health_part("auth") == "ready", 120, what="the stack back")


def stop(restored: list[str], name: str) -> None:
    service("stop", name)
    restored.append(name)


def start(restored: list[str], name: str) -> None:
    service("start", name)
    restored.remove(name)


def test_postgresql_restarts_and_nobody_is_signed_out(page, deed, restored):
    sign_in(page)
    upload(page, deed)
    stop(restored, "postgres")
    wait_until(lambda: health_part("history") == "failed", 30, what="/health noticing the database")
    # deleting a document while the conversations can't be read is refused with a sentence, nothing deleted
    r = page.request.get("/v1/documents")
    assert r.status == 503, r.status
    assert "database" in r.json().get("detail", "").lower() or r.json().get("reason") == "database"
    start(restored, "postgres")
    wait_until(lambda: health_part("history") == "ready" and health_part("documents") == "ready", 90, what="the stores reconnecting")
    # the same session, no new sign-in: the stores reconnected by themselves (Pod check of f0ff96c)
    assert page.request.get("/auth/me").ok
    assert page.request.get("/v1/documents").ok
    text = ask(page, "Hoe is het verkochte kadastraal bekend?")
    assert "sectie K, nummer 4182" in text
    # and a first upload after the restart works (Pod check of cbccd38: the retry left a copy in the inbox)
    page.get_by_role("button", name="New conversation or new case").click()
    page.get_by_role("menuitem", name="New conversation").click()
    upload(page, deed)


def test_a_sign_in_right_after_postgresql_restarts_works_first_time(page, restored):
    """Found by this suite on 2 November 2026: with its pool's connections dead after a PostgreSQL restart,
    Keycloak's first request failed (its 'internal server error' page on the first sign-in; 3 of 4 trials) until
    its pool had thrown the dead ones out. Fixed by checking a pooled connection before use
    (``quarkus.datasource.jdbc.validate-on-borrow``, set by the stack as the appliance sets it)."""
    kc_token()  # Keycloak holds a used connection in its pool when the database goes
    stop(restored, "postgres")
    wait_until(lambda: health_part("history") == "failed", 30, what="/health noticing the database")
    start(restored, "postgres")
    wait_until(lambda: health_part("history") == "ready", 90, what="the stores reconnecting")
    page.context.set_default_timeout(8_000)
    sign_in(page)


def test_keycloak_restarts_and_status_says_so_meanwhile(page, restored):
    sign_in(page)
    stop(restored, "keycloak")
    # /health asks Keycloak again, at most every 15 s: it must not keep saying sign-in works (round 2, finding 3)
    wait_until(lambda: health_part("auth") not in (None, "ready"), 40, what="/health noticing Keycloak is down")
    # the session that exists keeps working on the gateway's own routes meanwhile
    assert page.request.get("/auth/me").ok
    start(restored, "keycloak")
    wait_until(lambda: health_part("auth") == "ready" and health_part("directory") == "ready", 180, every=3, what="sign-in back")
    # a fresh sign-in works again
    other = page.context.browser.new_context(locale="en-GB", base_url=page.context._impl_obj._options.get("baseURL"))
    fresh = other.new_page()
    sign_in(fresh)
    other.close()


def test_the_model_server_is_away_and_the_answer_says_so(page, deed, restored):
    sign_in(page)
    upload(page, deed)
    stop(restored, "stub")
    wait_until(lambda: health_part("backend") in ("unreachable", "error", "failed"), 30, what="/health noticing the model server")
    text = ask(page, "Wat is de koopprijs?", timeout=60_000)
    # a failed answer is said in the interface's language with its reason, never the server's text (f83be07, finding 14)
    assert re.search(r"The answer failed: the model can't be reached", text), text[-400:]
    assert "Traceback" not in text and "ConnectError" not in text
    start(restored, "stub")
    wait_until(lambda: health_part("backend") == "ok", 30, what="the model server back")
    text = ask(page, "Wat is de koopprijs?")
    assert "EUR 1.275.000,00" in text


def test_the_sign_in_page_says_the_database_is_down(page, restored):
    """With PostgreSQL down, where Keycloak keeps its accounts, the sign-in page says so instead of sending the
    person to a Keycloak that can't answer (Pod check of 22 October)."""
    stop(restored, "postgres")
    wait_until(lambda: health_part("history") == "failed", 30, what="/health noticing the database")
    page.goto("/")
    page.wait_for_timeout(2000)
    body = page.locator("body").inner_text()
    assert "localhost:8180" not in page.url, "sent to Keycloak while its database is down"
    assert re.search(r"database|can't be reached|unavailable", body, re.I), body[:400]
    expect(page.get_by_role("button", name=re.compile("Try again", re.I))).to_be_visible()
