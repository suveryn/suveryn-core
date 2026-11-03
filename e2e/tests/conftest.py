"""Fixtures for the end-to-end scenarios (e2e/README.md). The stack is up already (``stack.py up``); these
tests only drive a browser against it and, for the lifecycle scenarios, stop and start its services.

    uv run --group e2e pytest e2e/tests -x
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

HERE = Path(__file__).resolve().parent
E2E = HERE.parent
ROOT = E2E.parent
RUN = E2E / ".run"
SHOTS = RUN / "shots"
sys.path.insert(0, str(E2E))
sys.path.insert(0, str(ROOT / "packages" / "rag" / "tests"))
from stack import ACCOUNTS, GATEWAY, PUBLIC_URL, gateway_health, seed_accounts  # noqa: E402

ADMIN, COLLEAGUE = ACCOUNTS
SLOW = 240_000  # ms: the real reader (Docling, OCR of the pasted scan) on a CI runner's CPU takes minutes for the deed


def pytest_configure(config):
    SHOTS.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session")
def deed() -> Path:
    """The fictional trap deed, with its injection attempt: the one document every scenario uploads."""
    import trap_deed

    path = RUN / "fixtures" / "akte-testdorp.pdf"
    if not path.exists():
        trap_deed.build(path, injected=True)
    return path


@pytest.fixture(scope="session")
def stack_up():
    try:
        h = gateway_health()
    except httpx.HTTPError as e:
        pytest.exit(f"the stack isn't up ({type(e).__name__}): run `uv run python e2e/stack.py up` first", returncode=3)
    assert h.get("status") == "ok", h
    seed_accounts()  # the accounts as the scenarios expect them, whatever an earlier run left


@pytest.fixture(scope="session")
def playwright():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright, stack_up):
    b = playwright.chromium.launch()
    yield b
    b.close()


@pytest.fixture
def context(browser, request):
    ctx = browser.new_context(locale="en-GB", viewport={"width": 1440, "height": 950}, base_url=PUBLIC_URL)
    ctx.set_default_timeout(20_000)
    yield ctx
    for i, page in enumerate(ctx.pages):
        try:
            page.screenshot(path=SHOTS / f"{request.node.name}-{i}.png", full_page=True)
        except Exception:  # noqa: BLE001 - a closed page has no screenshot
            pass
    ctx.close()


@pytest.fixture
def page(context):
    return context.new_page()


# --------------------------------------------------------------------------------------------- helpers

def sign_in(page, account: dict = ADMIN) -> None:
    """From the UI's root through Keycloak's sign-in page and back, as a person does."""
    page.goto("/")
    page.wait_for_url(re.compile(r"localhost:8180/realms/suveryn/"))
    page.get_by_label("Username or email").fill(account["username"])
    page.get_by_label("Password", exact=True).fill(account["password"])
    page.get_by_role("button", name="Sign In").click()
    page.wait_for_url(f"{PUBLIC_URL}/**")
    page.get_by_role("button", name=f"Account: {account['firstName']} {account['lastName']}").wait_for()


def sign_out(page) -> None:
    account_menu(page).get_by_role("menuitem", name=re.compile("Sign out")).click()
    box = dialog(page)
    if box.count():
        box.get_by_role("button", name=re.compile("Keep|Sign out")).first.click()
    page.wait_for_url(re.compile(r"localhost:8180/|localhost:5173/$"))


def dialog(page):
    """The open dialog, whichever role the kit gave it."""
    return page.locator("[role=dialog], [role=alertdialog]").last


def account_menu(page):
    page.locator("button.account-row").click()  # "Account: <name>" in the sidebar; Users has an "Account" filter too
    return page


def upload(page, pdf: Path, into_case: bool = False) -> None:
    """Add a document from the composer and wait until it is read (the card says so)."""
    card = page.get_by_text(pdf.name).first
    for attempt in range(2):
        page.locator("input[type=file]").first.set_input_files(str(pdf))
        try:
            card.wait_for(timeout=15_000)
            break
        except PlaywrightTimeoutError:
            if attempt:
                raise
            page.wait_for_timeout(1000)  # the first upload of a run on a cold page: choose the file once more
    page.get_by_text(re.compile(r"^(Read\.|Ready)"), exact=False).first.wait_for(timeout=SLOW)


def ask(page, question: str, timeout: int = 60_000) -> str:
    """Send a question and return the answer's text once the sources line or a failure appears."""
    done = page.get_by_text(re.compile(r"^Sources:|^The answer failed|couldn't be completed", re.I))
    before = done.count()
    box = page.get_by_role("textbox", name=re.compile("^Your question"))
    box.fill(question)
    page.get_by_role("button", name="Send message").click()
    expect(done).to_have_count(before + 1, timeout=timeout)
    return page.locator("main").inner_text()


def new_case(page, reference: str, name: str, subject: str = "Havenweg 12, Testdorp", kind: str = "Sale") -> None:
    page.get_by_role("button", name="New conversation or new case").click()
    page.get_by_role("menuitem", name="New case").click()
    page.get_by_label("Reference").fill(reference)
    page.get_by_label("Name", exact=True).fill(name)
    page.get_by_role("combobox", name="Type").fill(kind)
    option = page.get_by_role("option", name=re.compile(kind, re.I))
    if option.count():
        option.first.click()
    page.get_by_label("Subject").fill(subject)
    page.get_by_role("button", name="Open case").click()
    page.get_by_role("button", name=f"Case {reference}: actions").wait_for()


def open_case(page, reference: str) -> None:
    page.get_by_role("button", name="Cases").click()
    page.get_by_text(reference, exact=True).first.click()
    page.get_by_role("button", name=f"Case {reference}: actions").wait_for()


def administration(page, section: str) -> None:
    account_menu(page).get_by_role("menuitem", name="Administration").click()
    page.get_by_role("heading", name="Administration").wait_for()
    page.get_by_role("button", name=section, exact=True).first.click()
    page.get_by_role("heading", name=section, exact=True).first.wait_for()


def service(action: str, name: str) -> None:
    """``stack.py stop|start <service>``, with the stack's own environment."""
    subprocess.run([sys.executable, str(E2E / "stack.py"), action, name], check=True, env=os.environ)


def wait_until(probe, timeout: float = 60.0, every: float = 1.0, what: str = "condition") -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            if probe():
                return
        except Exception:  # noqa: BLE001
            pass
        time.sleep(every)
    raise AssertionError(f"{what}: not true after {timeout:.0f}s")


def health_part(part: str) -> str | None:
    try:
        return (gateway_health().get(part) or {}).get("status")
    except httpx.HTTPError:
        return None


__all__ = ["ADMIN", "COLLEAGUE", "GATEWAY", "PUBLIC_URL", "SLOW", "sign_in", "sign_out", "account_menu", "dialog", "upload", "ask",
           "new_case", "open_case", "administration", "service", "wait_until", "health_part"]
