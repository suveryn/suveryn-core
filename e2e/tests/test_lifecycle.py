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
from conftest import ask, database_back, health_part, service, sign_in, upload, wait_until
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
    wait_until(lambda: database_back() and health_part("documents") == "ready", 90, what="the stores reconnecting")
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
    wait_until(database_back, 90, what="the stores reconnecting")
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
    # Two right outcomes, depending on how soon the UI hears the model is gone (it asks once a minute): the
    # composer disabled with its notice, or a question sent and answered with the failure in words, never the
    # server's own text (f83be07, finding 14).
    send = page.get_by_role("button", name="Send message")
    page.get_by_role("textbox", name=re.compile("^Your question")).fill("Wat is de koopprijs?")
    if send.is_enabled():
        text = ask(page, "Wat is de koopprijs?", timeout=60_000)
        assert re.search(r"The answer failed: the model can't be reached|isn't available right now", text), text[-400:]
        assert "Traceback" not in text and "ConnectError" not in text
    else:
        expect(page.get_by_text("The model isn't available right now.")).to_be_visible()
    start(restored, "stub")
    wait_until(lambda: health_part("backend") == "ok", 30, what="the model server back")
    page.get_by_role("textbox", name=re.compile("^Your question")).fill("Wat is de koopprijs?")
    expect(send).to_be_enabled(timeout=90_000)  # the UI hears the model is back within its minute
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


def test_a_file_that_doesnt_arrive_reloads_the_page_once(page):
    """Found by this suite on 6 November 2026: right after a container restart, Chromium cancelled one of the app's
    files (ERR_NETWORK_CHANGED: Docker had changed the machine's network) and the app never started, a white page
    and no way to sign in. An office sees the same when a laptop changes Wi-Fi as sūveryn opens. public/boot.js
    reloads the page once; here one file is dropped on purpose and the person still reaches the sign-in."""
    dropped: list[str] = []

    def drop_once(route):
        if dropped:
            route.continue_()
        else:
            dropped.append(route.request.url)
            route.abort("internetdisconnected")

    page.route(re.compile(r"/assets/i18n-[^/]*\.js$"), drop_once)
    sign_in(page)
    assert dropped, "the test dropped nothing: the i18n chunk is named differently now"

