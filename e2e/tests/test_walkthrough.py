"""The walk-through: what a VM regression round does by hand, through the browser against the stack
(e2e/README.md). Sign in, a document and a cited answer, a case with a colleague, deed intake to its summary,
Administration, a switched-off account's session ending at once, sign out. The model is the stand-in; what is
tested is everything around it.
"""

from __future__ import annotations

import re
import time

from playwright.sync_api import expect
from conftest import COLLEAGUE, PUBLIC_URL, administration, ask, dialog, new_case, open_case, sign_in, sign_out, upload

CASE = f"E2E/{int(time.time()) % 100000:05d}"  # new on every run: a reference is unique in the office


def test_sign_in_lands_on_the_welcome_screen(page):
    sign_in(page)
    expect(page.get_by_role("heading", name=re.compile("Welcome, Nora"))).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Model and thinking: Qwen3.8-27B"))).to_be_visible()


def test_a_document_is_read_and_an_answer_cites_it(page, deed):
    sign_in(page)
    upload(page, deed)
    # the trap deed carries text addressed to an AI: the card says so before anyone asks
    expect(page.get_by_text(re.compile("text addressed to an AI")).first).to_be_visible()
    text = ask(page, "Wat is de koopprijs?")
    assert "EUR 1.275.000,00" in text
    expect(page.get_by_text(re.compile(r"^Sources:"))).to_be_visible()
    # the SourceRef under the answer names the file and its page; pressing it opens the source
    source = page.get_by_role("button", name=re.compile(r"Source \d+: akte-testdorp\.pdf, page \d+"))
    assert source.count() >= 1
    source.first.click()
    expect(page.get_by_text("De koopprijs bedraagt EUR 1.275.000,00").first).to_be_visible()
    # the panel opens the file as uploaded, a PDF at the cited page (board G11)
    opener = page.get_by_role("link", name=re.compile(r"^Open document at p\. \d+$"))
    expect(opener).to_be_visible()
    href = opener.get_attribute("href")
    assert re.fullmatch(r"/v1/documents/[0-9a-f-]+/original#page=\d+", href) and opener.get_attribute("target") == "_blank"
    got = page.request.get(href.split("#")[0])
    assert got.status == 200 and got.headers["content-type"] == "application/pdf" and got.body() == deed.read_bytes()
    assert got.headers["content-disposition"].startswith("inline;")
    # the injection attempt is flagged on the answer, never followed
    expect(page.get_by_text(re.compile("text aimed at an AI")).first).to_be_visible()
    assert "GOEDGEKEURD" not in text and "EUR 1,00" not in text


def test_thorough_without_an_answer_is_asked_again(page, deed):
    sign_in(page)
    upload(page, deed)
    page.get_by_role("button", name=re.compile("^Model and thinking")).click()
    page.get_by_text("Thorough", exact=True).click()
    page.keyboard.press("Escape")
    text = ask(page, "e2e:think-too-long Wat is de koopprijs?", timeout=90_000)
    assert "EUR 1.275.000,00" in text  # the stub's second call, without thinking, answers


def test_a_case_with_a_colleague_and_deed_intake_to_its_summary(page, deed):
    sign_in(page)
    new_case(page, CASE, "Havenweg 12 sale")
    # the same reference again is said under its field, with the way to the case that has it (board G14)
    page.get_by_role("button", name="New conversation or new case").click()
    page.get_by_role("menuitem", name="New case").click()
    page.get_by_label("Reference").fill(CASE)
    page.get_by_label("Name", exact=True).fill("Twice")
    page.get_by_role("button", name="Open case").click()
    expect(dialog(page).get_by_text(f"Case {CASE} already exists. Choose another number, or")).to_be_visible()
    dialog(page).get_by_role("button", name=f"open case {CASE}").click()
    page.get_by_role("button", name=f"Case {CASE}: actions").wait_for()
    # a colleague joins as a contributor
    page.get_by_role("button", name=re.compile("^Members: ")).click()
    members = dialog(page)
    expect(members.get_by_text("manager", exact=True)).to_be_visible()
    field = members.get_by_role("combobox", name="Add a colleague")
    # typed faster than the directory answers (about 300 ms): the suggestions open when they arrive, no key needed
    # (found writing this suite; the kit's ComboBoxField opens on late suggestions)
    field.fill("Koen")
    page.get_by_role("option", name=re.compile("Koen Collega")).click()
    members.get_by_role("button", name="Add", exact=True).click()
    expect(members.get_by_text("Koen Collega")).to_be_visible()
    members.get_by_role("button", name="Close").click()
    expect(page.get_by_role("button", name=re.compile(r"^Members: Nora Notaris \(case manager\), Koen Collega"))).to_be_visible()
    # the deed goes into the case, and the playbook runs as a conversation
    upload(page, deed, into_case=True)
    page.get_by_role("button", name="Apply a playbook to this case").click()
    page.get_by_role("menuitem", name=re.compile("^Deed intake")).click()
    page.get_by_text("Nora Notaris started Deed intake").wait_for()
    page.get_by_role("button", name="Use the documents already in the case").click()
    # the parties and the conditions are lists; a list is one fact (board P01), so the count is the thirteen facts
    page.get_by_text(re.compile(r"\d+ of 13 facts found\. Not in the documents:")).wait_for(timeout=120_000)
    # the facts the documents lack are asked; "Not known yet" answers each question until the review
    for _ in range(18):
        button = page.get_by_role("button", name="Not known yet")
        if not button.count():
            break
        button.first.click()
        page.wait_for_timeout(500)
    review = page.get_by_text(re.compile(r"\d+ need your attention:"))
    review.wait_for()
    expect(page.get_by_text("Energy certificate").first).to_be_visible()  # a fact the trap deed never mentions
    page.get_by_role("button", name="See all 13 facts").click()
    expect(page.get_by_text("EUR 1.275.000,00").first).to_be_visible()   # the price, read from the deed
    expect(page.locator("#run-panel [data-fact='sellers']")).to_be_visible()  # a list as one block (board P03)
    page.keyboard.press("Escape")
    page.get_by_role("button", name="Confirm the facts").click()
    page.get_by_text(re.compile("Confirmed by Nora Notaris")).wait_for()
    expect(page.get_by_text("The summary is in the case's documents.")).to_be_visible()
    expect(page.get_by_role("button", name=f"2 documents in case {CASE}")).to_be_visible()


def test_the_colleague_reads_the_case_and_its_summary(page, deed):
    sign_in(page, COLLEAGUE)
    open_case(page, CASE)
    page.get_by_role("button", name=f"2 documents in case {CASE}").click()
    # the summary is in the case's documents, made by the playbook, never a source
    expect(page.get_by_text(f"Deed intake {CASE} (1.4)")).to_be_visible()
    expect(page.get_by_text("Not a source", exact=True)).to_be_visible()
    expect(page.get_by_text("akte-testdorp.pdf")).to_be_visible()


def test_administration_pages_open_and_status_is_sound(page):
    sign_in(page)
    for section in ("Users", "Cases", "Playbooks", "Usage", "Settings", "Status", "Backups"):
        administration(page, section)
    administration(page, "Status")
    for check in ("Answering questions", "Reading documents", "Signing in", "Keeping your data"):
        expect(page.get_by_text(check, exact=True)).to_be_visible()
    assert page.locator("main").inner_text().count("Working") >= 4
    expect(page.get_by_text("e2e", exact=True)).to_be_visible()  # SUVERYN_VERSION, in the overview
    administration(page, "Playbooks")
    expect(page.get_by_text(re.compile("Deed intake 1.4")).first).to_be_visible()


def test_a_price_typed_and_saved_without_leaving_the_field_is_saved(page):
    """Board B08, Filip's review of 6 November: after typing a price, Save stayed grey, because the field only
    committed its number on blur and a click on a disabled button doesn't take the focus. Typed, then Save at once."""
    sign_in(page)
    administration(page, "Settings")
    field = page.get_by_label("Per million input tokens")
    before = field.input_value()
    save = page.get_by_role("button", name="Save", exact=True)
    field.click()
    field.press("ControlOrMeta+a")
    field.press_sequentially("3.5")
    expect(field).to_be_focused()
    expect(save).to_be_enabled()
    save.click()
    expect(page.get_by_text("Saved.", exact=True)).to_be_visible()
    rates = page.request.get("/v1/admin/usage/rates").json()
    assert float(rates["input_per_million"]) == 3.5, rates
    # put it back, so the usage scenarios see the stack's own price
    field.click()
    field.press("ControlOrMeta+a")
    field.press_sequentially(before or "0")
    with page.expect_response(lambda r: r.url.endswith("/v1/admin/usage/rates") and r.request.method != "GET"):
        save.click()


def test_full_width_pages_fold_the_column_and_a_personal_conversation_has_its_title_bar(page):
    """Claude Design's build instruction of 6 November: on Administration (and Conversations, Cases, Documents) the
    column is the rail, so the page gets the width (G06 to G08, the B boards); Administration › Cases changes the
    office's case settings in place (B05); a personal conversation has a title bar whose chevron opens its menu (G03)."""
    sign_in(page)
    administration(page, "Cases")
    expect(page.get_by_role("button", name="Expand the sidebar")).to_be_visible()
    expect(page.get_by_role("button", name=re.compile("Who sees a case$"))).to_be_visible()
    page.get_by_role("button", name="Expand the sidebar").click()     # the column on this page only
    expect(page.get_by_role("button", name="Collapse the sidebar")).to_be_visible()
    page.get_by_role("button", name="Conversations", exact=True).click()
    expect(page.get_by_role("button", name="Expand the sidebar")).to_be_visible()
    page.get_by_role("button", name="Expand the sidebar").click()
    page.get_by_role("button", name="New conversation or new case").click()
    page.get_by_role("menuitem", name="New conversation").click()
    # a question without documents: the answer has no "Sources:" line (``ask`` waits for one), so wait for the
    # title bar instead, which comes once the conversation is saved after the answer
    page.get_by_role("textbox", name=re.compile("^Your question")).fill("Wat is een huurkoopformule?")
    page.get_by_role("button", name="Send message").click()
    menu = page.locator("main").get_by_role("button", name=re.compile("^Actions for"))
    expect(menu).to_be_visible(timeout=60_000)
    menu.click()
    for item in ("Pin", "Rename", "Move to a case", "Delete"):
        expect(page.get_by_role("menuitem", name=re.compile(f"^{item}"))).to_be_visible()
    page.keyboard.press("Escape")


def test_an_account_switched_off_loses_its_session_at_once(page, browser):
    # the colleague is signed in on a second browser
    other = browser.new_context(locale="en-GB", base_url=PUBLIC_URL)
    colleague = other.new_page()
    sign_in(colleague, COLLEAGUE)
    assert colleague.request.get("/auth/me").ok
    # the administrator switches the account off
    sign_in(page)
    administration(page, "Users")
    page.get_by_role("button", name="Actions for Koen Collega").click()
    page.get_by_role("menuitem", name=re.compile("Switch account off")).click()
    dialog(page).get_by_role("button", name="Switch off").click()
    page.get_by_text(re.compile("Koen Collega")).first.wait_for()
    # within seconds, not minutes: the gateway ends its own sessions (VM check of 28 October, finding 2)
    deadline = 15
    for _ in range(deadline):
        r = colleague.request.get("/auth/me", max_redirects=0)
        if r.status in (401, 302, 303):
            break
        colleague.wait_for_timeout(1000)
    assert r.status in (401, 302, 303), f"the session still works after {deadline}s: HTTP {r.status}"
    other.close()
    # and back on, so later scenarios can use the account: the list shows accounts that are on, so filter first
    page.locator("button.ui-select-button").filter(has_text="Account:").click()
    page.get_by_role("option", name=re.compile("Off")).click()
    page.get_by_role("button", name="Actions for Koen Collega").click()
    page.get_by_role("menuitem", name=re.compile("Switch account on")).click()
    dialog(page).get_by_role("button", name="Switch account on").click()
    expect(page.get_by_text("1 user")).not_to_be_visible()


def test_a_new_account_signs_in_with_a_temporary_password(page, browser):
    stamp = int(time.time()) % 100000
    email = f"pieter{stamp}@example.test"
    sign_in(page)
    administration(page, "Users")
    page.get_by_role("button", name="Add user").click()
    page.locator("input[name=name]").fill("Pieter Proef")
    page.locator("input[name=email]").fill(email)
    page.get_by_role("button", name="Add", exact=True).click()
    # the temporary password is shown once, to pass on
    sheet = dialog(page)
    expect(sheet.get_by_text("Pass this on to Pieter Proef")).to_be_visible()
    temporary = sheet.get_by_text("Temporary password").locator("xpath=following-sibling::*[1]").inner_text().strip()
    assert len(temporary) >= 12, temporary
    sheet.get_by_role("button", name="Done").click()
    other = browser.new_context(locale="en-GB", base_url=PUBLIC_URL)
    new = other.new_page()
    new.goto("/")
    new.get_by_label("Username or email").fill(email)
    new.get_by_label("Password", exact=True).fill(temporary)
    new.get_by_role("button", name="Sign In").click()
    # Keycloak asks for a new password at the first sign-in
    new.get_by_label("New Password", exact=True).fill("Pieter-e2e-2026!!")
    new.get_by_label("Confirm password", exact=True).fill("Pieter-e2e-2026!!")
    new.get_by_role("button", name="Submit").click()
    new.wait_for_url(f"{PUBLIC_URL}/**")
    new.get_by_role("button", name="Account: Pieter Proef").wait_for()
    other.close()


def test_sign_out_ends_the_session(page):
    sign_in(page)
    sign_out(page)
    assert page.request.get("/auth/me", max_redirects=0).status == 401
