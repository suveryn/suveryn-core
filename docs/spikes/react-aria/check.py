"""Browser checks for the web setup and the chat's model menu (suveryn-tracker#37, #44), against a build
served with the appliance's real CSP (serve.py). Prints each check, writes report.json and screenshots.

The setup needs the preview build, whose demo answers stand in for the appliance (src/setup/demo.ts):

    npm run build -- --mode demo --outDir /tmp/setup-demo
    python3 serve.py /tmp/setup-demo 8765 <suveryn-appliance>/reverse-proxy &
    python3 check.py http://127.0.0.1:8765 <out-dir>   # Python Playwright with Chromium, and axe-core:
    AXE_JS=<path to axe-core/axe.min.js>                # npm install axe-core@4.10.3 in any folder
"""
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE, OUT = sys.argv[1], Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
AXE = Path(os.environ.get("AXE_JS", Path(__file__).parent / "node_modules/axe-core/axe.min.js"))
INIT = """window.__violations=[];document.addEventListener('securitypolicyviolation',e=>window.__violations.push(
  e.violatedDirective+' blocked '+(e.blockedURI||'inline')+' '+(e.sample||'').slice(0,60)));"""
IOS = """Object.defineProperty(navigator,'userAgentData',{get:()=>undefined});Object.defineProperty(navigator,'platform',{get:()=>'iPhone'});Object.defineProperty(navigator,'maxTouchPoints',{get:()=>5});"""
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/18.5 Mobile/15E148 Safari/604.1")
results, violations, errors = [], {}, []


def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""), flush=True)


def focused(pg):
    return pg.evaluate("""() => { const e = document.activeElement; if (!e) return null;
      const lab = e.labels && e.labels[0] ? e.labels[0].innerText.split('\\n')[0] : '';
      return { tag: e.tagName.toLowerCase(), role: e.getAttribute('role') || e.type || '',
               name: (e.getAttribute('aria-label') || lab || e.innerText || '').trim().split('\\n')[0].slice(0, 60),
               invalid: e.getAttribute('aria-invalid'), describedby: e.getAttribute('aria-describedby') }; }""")


def new_page(browser, name, **ctx):
    c = browser.new_context(**ctx)
    pg = c.new_page()
    pg.add_init_script(INIT)
    if ctx.get("user_agent") == IPHONE_UA:
        pg.add_init_script(IOS)
    pg.on("pageerror", lambda e: errors.append(f"{name}: {e}"))
    pg.on("console", lambda m: m.type == "error" and errors.append(f"{name}: {m.text}"))
    return pg


def done(pg, name):
    v = pg.evaluate("window.__violations")
    violations[name] = v
    pg.context.close()


def tab_until(pg, pred, limit=12):
    seq = []
    for _ in range(limit):
        pg.keyboard.press("Tab")
        f = focused(pg)
        seq.append(f)
        if pred(f):
            return f, seq
    return None, seq


def setup_keyboard(browser):
    """Steps 1 and 2 with the keyboard only, in English."""
    pg = new_page(browser, "setup, keyboard", viewport={"width": 1280, "height": 900}, locale="en-GB")
    pg.goto(f"{BASE}/setup.html")
    pg.get_by_role("heading", name="Set up your sūveryn appliance", level=1).wait_for()
    pg.screenshot(path=OUT / "setup-0-en.png", full_page=True)
    order = [focused(pg) for _ in range(2) if pg.keyboard.press("Tab") is None]
    check("welcome: Tab goes language menu, Get started", [o["name"] for o in order] == ["English Language", "Get started"]
          or [o["name"] for o in order][1] == "Get started", json.dumps(order))
    pg.keyboard.press("Enter")
    pg.get_by_role("heading", name="Network", level=1).wait_for()
    pg.wait_for_timeout(200)
    check("step 1: the focus moves to its heading", focused(pg)["tag"] == "h1")
    pg.screenshot(path=OUT / "setup-1-en.png", full_page=True)

    order = []
    for _ in range(4):
        pg.keyboard.press("Tab")
        order.append(focused(pg))
    names = [f"{o['role']}:{o['name']}" for o in order]
    check("step 1: from its heading, Tab goes internet access, outgoing connections, Back, Continue",
          [o["role"] for o in order] == ["radio", "radio", "button", "submit"] and order[0]["name"].startswith("Connected")
          and order[1]["name"].startswith("Approved"), " → ".join(names))

    pg.keyboard.press("Shift+Tab"); pg.keyboard.press("Shift+Tab"); pg.keyboard.press("Shift+Tab")  # back to Connected
    pg.keyboard.press("ArrowDown")
    pg.wait_for_timeout(200)
    f = focused(pg)
    detail_gone = pg.get_by_text("Outgoing connections", exact=True).count() == 0
    check("step 1: ArrowDown chooses Air-gapped; the outgoing options go away",
          f["name"].startswith("Air-gapped") and pg.get_by_role("radio", name="Air-gapped").is_checked() and detail_gone,
          f"{json.dumps(f)} checked {pg.get_by_role('radio', name='Air-gapped').is_checked()} detail gone {detail_gone}")
    pg.keyboard.press("ArrowUp")
    check("step 1: ArrowUp back to Connected; the outgoing options come back",
          pg.get_by_role("radio", name="Connected").is_checked() and pg.get_by_role("radiogroup", name="Outgoing connections").count() == 1)
    pg.keyboard.press("Tab"); pg.keyboard.press("ArrowDown")
    check("step 1: ArrowDown in outgoing connections chooses Allow all",
          pg.get_by_role("radio", name="Allow all outgoing traffic").is_checked())
    pg.keyboard.press("Tab"); pg.keyboard.press("Tab"); pg.keyboard.press("Enter")

    pg.get_by_role("heading", name="Administrator account", level=1).wait_for()
    f = focused(pg)
    check("step 2: the focus starts on its heading (screen readers read it first)", f and f["tag"] == "h1", json.dumps(f))
    pg.screenshot(path=OUT / "setup-2-en.png", full_page=True)

    # Errors only on Continue: type a short password and move on; nothing shows.
    f, seq = tab_until(pg, lambda f: f["name"] == "Password")
    pg.keyboard.type("short")
    pg.keyboard.press("Tab")
    check("step 2: no error while typing or leaving a field", pg.locator(".ui-field-error").count() == 0)
    # Show/hide toggle: the Tab after the password field.
    f = focused(pg)
    pressed_before = pg.get_by_role("button", name="Show password").get_attribute("aria-pressed")
    pg.keyboard.press("Space")
    shown = pg.locator("input[name=password]").get_attribute("type")
    check("step 2: the show/hide toggle is a toggle button after the field; Space shows the password",
          f["name"] == "Show password" and pressed_before == "false" and shown == "text"
          and pg.get_by_role("button", name="Show password").get_attribute("aria-pressed") == "true", json.dumps(f))
    pg.keyboard.press("Space")

    # Continue with everything wrong: errors under each field, focus to the first.
    f, seq = tab_until(pg, lambda f: f["role"] == "submit")
    pg.keyboard.press("Enter")
    pg.locator(".ui-field-error").first.wait_for()
    f = focused(pg)
    errs = pg.locator(".ui-field-error").all_inner_texts()
    check("step 2: Continue shows the errors and moves the focus to the first field in error",
          f["name"] == "Full name" and f["invalid"] == "true" and len(errs) == 3, f"{json.dumps(f)} {errs}")
    err_id = pg.evaluate("""() => { const i = document.querySelector('input[name=password]');
        const ids = (i.getAttribute('aria-describedby')||'').split(' ');
        return ids.map(id => document.getElementById(id)?.innerText || '').join(' | '); }""")
    check("step 2: each error is tied to its field (aria-describedby), so it is read with it",
          "15 characters" in err_id, err_id)
    pg.screenshot(path=OUT / "setup-2-errors-en.png", full_page=True)

    pg.keyboard.type("Filip Tack")
    pg.keyboard.press("Tab")
    check("step 2: changing a field and leaving it clears its error", pg.locator(".ui-field-error").count() == 2)
    pg.keyboard.type("filip@firm.example")
    pg.keyboard.press("Tab"); pg.keyboard.press("Control+A"); pg.keyboard.type("my notary office password")
    pg.keyboard.press("Tab"); pg.keyboard.press("Tab"); pg.keyboard.type("my notary office password")
    f, seq = tab_until(pg, lambda f: f["role"] == "submit")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(300)
    errs = pg.locator(".ui-field-error").all_inner_texts()
    check("step 2: the appliance's name in the password is refused", any("appliance" in e for e in errs), str(errs))
    pg.locator("input[name=password]").focus()
    pg.keyboard.press("Control+A"); pg.keyboard.type("violet harbour lantern 47")
    pg.locator("input[name=confirm]").focus(); pg.keyboard.press("Control+A"); pg.keyboard.type("violet harbour lantern 47")
    pg.keyboard.press("Tab"); pg.keyboard.press("Tab"); pg.keyboard.press("Enter")
    pg.get_by_role("heading", name="Certificate", level=1).wait_for()
    check("step 2: a good account is saved and continues to step 3", True)
    done(pg, "setup, keyboard (en)")


def setup_languages(browser):
    """The language menu with the keyboard, then Dutch and French errors."""
    pg = new_page(browser, "setup, languages", viewport={"width": 1280, "height": 900}, locale="en-GB")
    pg.goto(f"{BASE}/setup.html")
    pg.get_by_role("heading", name="Set up your sūveryn appliance", level=1).wait_for()
    pg.keyboard.press("Tab")
    pg.keyboard.press("Enter")
    lb = pg.get_by_role("listbox")
    lb.wait_for()
    opts = pg.get_by_role("option").all_inner_texts()
    pg.keyboard.press("ArrowDown"); pg.keyboard.press("Enter")
    pg.get_by_role("heading", name="Uw sūveryn-appliance instellen", level=1).wait_for()
    pg.wait_for_timeout(300)
    f = focused(pg)
    check("language menu: Enter opens a listbox (English, Nederlands, Français); ArrowDown, Enter switches to Dutch",
          opts == ["English", "Nederlands", "Français"], str(opts))
    check("language menu: the page follows at once (lang nl-BE, title) and the focus returns to the menu",
          pg.evaluate("document.documentElement.lang") == "nl-BE" and pg.title().endswith("instellen")
          and f["role"] == "button", f"{pg.evaluate('document.documentElement.lang')} {pg.title()} {json.dumps(f)}")
    pg.screenshot(path=OUT / "setup-0-nl.png", full_page=True)
    pg.get_by_role("button", name="Beginnen").click()
    pg.get_by_role("heading", name="Netwerk", level=1).wait_for()
    pg.screenshot(path=OUT / "setup-1-nl.png", full_page=True)
    pg.get_by_role("button", name="Verder").click()
    pg.get_by_role("heading", name="Beheerdersaccount").wait_for()
    pg.locator("input[name=name]").fill("Filip Tack")
    pg.locator("input[name=email]").fill("filip@kantoor")
    pg.locator("input[name=password]").fill("filip tack 12345678")
    pg.get_by_role("button", name="Verder").click()
    pg.locator(".ui-field-error").first.wait_for()
    nl = pg.locator(".ui-field-error").all_inner_texts()
    check("Dutch: the errors are in Dutch", nl == ["Vul een e-mailadres in zoals naam@voorbeeld.be.",
                                                   "Gebruik uw naam, uw e-mailadres of de naam van de appliance niet in het wachtwoord."], str(nl))
    pg.screenshot(path=OUT / "setup-2-errors-nl.png", full_page=True)
    # French, through the menu with the mouse this time
    pg.get_by_role("button", name="Taal").click() if pg.get_by_role("button", name="Taal").count() else pg.locator(".ui-select-button").click()
    pg.get_by_role("option", name="Français").click()
    pg.get_by_role("heading", name="Compte administrateur").wait_for()
    fr = pg.locator(".ui-field-error").all_inner_texts()
    check("French: switching language keeps the answers; the errors follow on the next Continue",
          pg.locator("input[name=name]").input_value() == "Filip Tack", str(fr))
    pg.get_by_role("button", name="Continuer").click()
    pg.wait_for_timeout(300)
    fr = pg.locator(".ui-field-error").all_inner_texts()
    check("French: the errors are in French", fr == ["Saisissez une adresse e-mail comme nom@exemple.be.",
                                                     "N'utilisez pas votre nom, votre adresse e-mail ni le nom de l'appliance dans le mot de passe."], str(fr))
    pg.screenshot(path=OUT / "setup-2-errors-fr.png", full_page=True)
    done(pg, "setup, languages")


def fits(pg, label):
    w = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    check(f"phone: {label} fits 375 px (no sideways scrolling)", w[0] <= w[1], str(w))


def fill_to(pg, last, lang="en"):
    """Answers the steps with the mouse (the demo answers for the appliance) up to the screen `last`."""
    L = LABELS[lang]
    pg.goto(f"{BASE}/setup.html" + ("#" + pg.variant if getattr(pg, "variant", None) else ""))
    pg.get_by_role("button", name=L["start"]).click()
    steps = [("network", None), ("admin", None), ("cert", None), ("support", None), ("backups", None), ("review", None)]
    for name, _ in steps:
        pg.get_by_role("heading", name=L[name], level=1).wait_for()
        if name == last:
            return
        if name == "admin":
            pg.locator("input[name=name]").fill("Filip Tack"); pg.locator("input[name=email]").fill("filip@firm.example")
            pg.locator("input[name=password]").fill("violet harbour lantern 47"); pg.locator("input[name=confirm]").fill("violet harbour lantern 47")
        if name == "backups":
            pg.get_by_role("button", name=L["download"]).click()
            pg.locator(".ui-checkbox").click()
        if name == "review":
            return
        pg.get_by_role("button", name=L["continue"]).click()


LABELS = {
    "en": {"start": "Get started", "continue": "Continue", "download": "Download the recovery key", "network": "Network",
           "admin": "Administrator account", "cert": "Certificate", "support": "Support agreement", "backups": "Backups",
           "review": "Review", "go": "Start provisioning", "prov": "Setting up the sūveryn appliance", "complete": "Setup complete"},
    "fr": {"start": "Commencer", "continue": "Continuer", "download": "Télécharger la clé de récupération", "network": "Réseau",
           "admin": "Compte administrateur", "cert": "Certificat", "support": "Contrat de support", "backups": "Sauvegardes",
           "review": "Récapitulatif", "go": "Lancer la mise en service", "prov": "Mise en service de l'appliance sūveryn",
           "complete": "Configuration terminée"},
}


def setup_phone(browser):
    """Phone width (375 px), as an iPhone, in French (the longest copy): every screen fits; React Aria's
    scroll lock works without a <style>."""
    pg = new_page(browser, "setup, phone", viewport={"width": 375, "height": 812}, user_agent=IPHONE_UA,
                  is_mobile=True, has_touch=True, device_scale_factor=2, locale="fr-BE", accept_downloads=True)
    L = LABELS["fr"]
    pg.goto(f"{BASE}/setup.html")
    pg.get_by_role("heading", name="Configurer votre appliance sūveryn", level=1).wait_for()
    fits(pg, "welcome in French")
    pg.screenshot(path=OUT / "setup-0-fr-phone.png", full_page=True)
    pg.locator(".ui-select-button").tap()
    pg.get_by_role("listbox").wait_for()
    attr = pg.evaluate("document.documentElement.hasAttribute('data-ui-prevent-scroll')")
    styles = pg.evaluate("document.querySelectorAll('style').length")
    check("iPhone: an open menu locks scrolling through the attribute, with no <style> element", attr and styles == 0,
          f"attribute {attr}, <style> elements {styles}")
    pg.get_by_role("option", name="Français").tap()
    pg.wait_for_timeout(300)
    check("iPhone: closing the menu removes the attribute",
          not pg.evaluate("document.documentElement.hasAttribute('data-ui-prevent-scroll')"))
    pg.get_by_role("button", name=L["start"]).tap()
    for name, shot in (("network", "1"), ("admin", "2"), ("cert", "3"), ("support", "4"), ("backups", "5"), ("review", "6")):
        pg.get_by_role("heading", name=L[name], level=1).wait_for()
        pg.wait_for_timeout(200)
        if name == "admin":
            pg.get_by_role("button", name=L["continue"]).tap()
            pg.locator(".ui-field-error").first.wait_for()
            fits(pg, "step 2 with its errors in French")
            pg.screenshot(path=OUT / "setup-2-errors-fr-phone.png", full_page=True)
            pg.locator("input[name=name]").fill("Filip Tack"); pg.locator("input[name=email]").fill("filip@firm.example")
            pg.locator("input[name=password]").fill("violet harbour lantern 47"); pg.locator("input[name=confirm]").fill("violet harbour lantern 47")
        elif name == "backups":
            pg.get_by_text("Partage réseau", exact=True).tap()
            pg.wait_for_timeout(200)
            fits(pg, "step 5 with a network share in French")
            pg.screenshot(path=OUT / "setup-5-share-fr-phone.png", full_page=True)
            pg.get_by_text("Disque USB", exact=True).tap()
            pg.get_by_role("button", name=L["download"]).tap()
            pg.locator(".ui-checkbox").tap()
        else:
            fits(pg, f"step {shot} in French")
        pg.screenshot(path=OUT / f"setup-{shot}-fr-phone.png", full_page=True)
        pg.get_by_role("button", name=L["go"] if name == "review" else L["continue"]).tap()
    pg.get_by_role("heading", name=L["prov"], level=1).wait_for()
    pg.wait_for_timeout(1600)
    fits(pg, "provisioning in French")
    pg.screenshot(path=OUT / "setup-7-fr-phone.png", full_page=True)
    pg.get_by_role("heading", name=L["complete"], level=1).wait_for(timeout=20000)
    fits(pg, "complete in French")
    pg.screenshot(path=OUT / "setup-8-fr-phone.png", full_page=True)
    done(pg, "setup, phone (iPhone, fr)")


def setup_flow(browser):
    """Screens 3 to 8 in English: errors, uploads, the recovery key, the share test, Edit from the review,
    provisioning and the finished state."""
    ctx = {"viewport": {"width": 1280, "height": 900}, "locale": "en-GB", "accept_downloads": True,
           "permissions": ["clipboard-read", "clipboard-write"]}
    pg = new_page(browser, "setup, flow", **ctx)
    fill_to(pg, "cert")
    pg.screenshot(path=OUT / "setup-3-en.png", full_page=True)
    pg.get_by_role("radio", name="Generate a self-signed certificate").focus()
    pg.keyboard.press("ArrowDown")
    pg.get_by_role("button", name="Continue").click()
    pg.locator(".ui-field-error").first.wait_for()
    f = focused(pg)
    errs = pg.locator(".ui-field-error").all_inner_texts()
    check("step 3: own certificate without files: both missing, the focus on the first file's button",
          errs == ["Choose the certificate file.", "Choose the private key file."] and f["name"].startswith("Choose file"),
          f"{errs} {json.dumps(f)}")
    pg.screenshot(path=OUT / "setup-3-errors-en.png", full_page=True)
    def pick(button_index, name, text):
        with pg.expect_file_chooser() as fc:
            pg.get_by_role("button", name="Choose file").nth(button_index).click()
        fc.value.set_files(files=[{"name": name, "mimeType": "application/x-pem-file", "buffer": text.encode()}])
    pick(0, "office.crt", "not a certificate")
    pick(1, "office.key", "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n")
    check("step 3: choosing a file clears its error and shows its name",
          pg.get_by_text("office.crt").count() == 1 and pg.locator(".ui-field-error").count() == 0)
    pg.get_by_role("button", name="Continue").click()
    pg.locator(".ui-field-error").first.wait_for()
    check("step 3: the appliance's refusal shows under the file it is about",
          pg.locator(".ui-field-error").all_inner_texts() == ["This isn't a certificate in PEM format."],
          str(pg.locator(".ui-field-error").all_inner_texts()))
    pick(0, "office.crt", "-----BEGIN CERTIFICATE-----\nx\n-----END CERTIFICATE-----\n")
    pg.get_by_role("button", name="Continue").click()

    pg.get_by_role("heading", name="Support agreement", level=1).wait_for()
    pg.screenshot(path=OUT / "setup-4-en.png", full_page=True)
    qr = pg.get_by_role("img", name="QR code to register this appliance in the sūveryn portal")
    check("step 4: the QR code is SVG in the page, with a name", qr.count() == 1 and qr.evaluate("e => e.tagName") == "svg")
    pg.get_by_role("button", name="Copy both").click()
    pg.wait_for_timeout(200)
    clip = pg.evaluate("navigator.clipboard.readText()")
    check("step 4: Copy both copies the ID and the fingerprint, and says so",
          clip.startswith("7f3c9a2e-") and "SHA256:42a9" in clip and pg.get_by_role("status").filter(has_text="Copied").count() >= 1, clip)
    with pg.expect_file_chooser() as fc:
        pg.get_by_role("button", name="choose a file").click()
    fc.value.set_files(files=[{"name": "manifest.txt", "mimeType": "text/plain", "buffer": b"x"}])
    pg.get_by_role("alert").filter(has_text="manifest").wait_for()
    check("step 4: a wrong file is refused, said at once (alert)", pg.get_by_text("This isn't a manifest file (.yaml).").count() == 1)
    with pg.expect_file_chooser() as fc:
        pg.get_by_role("button", name="choose a file").click()
    fc.value.set_files(files=[{"name": "manifest.yaml", "mimeType": "application/x-yaml", "buffer": b"edition: x"}])
    pg.get_by_text("Enabled named accounts").wait_for()
    check("step 4: a manifest shows the agreement (users, valid until, check-in, certified)",
          all(pg.get_by_text(t).count() for t in ("Sūveryn Enterprise", "30 September 2027", "31 December 2026", "3 connectors · 4 playbooks")))
    pg.screenshot(path=OUT / "setup-4-manifest-en.png", full_page=True)
    pg.get_by_role("button", name="Continue").click()

    pg.get_by_role("heading", name="Backups", level=1).wait_for()
    pg.screenshot(path=OUT / "setup-5-en.png", full_page=True)
    pg.get_by_role("button", name="Continue").click()
    pg.locator(".ui-field-error").first.wait_for()
    f = focused(pg)
    check("step 5: Continue without the key downloaded says so, the focus on Download",
          pg.locator(".ui-field-error").all_inner_texts() == ["Download the recovery key first."] and f["name"] == "Download the recovery key",
          f"{pg.locator('.ui-field-error').all_inner_texts()} {json.dumps(f)}")
    with pg.expect_download() as dl:
        pg.keyboard.press("Enter")
    key = Path(dl.value.path()).read_text()
    check("step 5: Download gives an age identity file named after the appliance",
          dl.value.suggested_filename == "suveryn-backup-recovery-key-notary-brussels-01.txt"
          and key.strip().splitlines()[-1].startswith("AGE-SECRET-KEY-1") and "# public key: age1" in key,
          dl.value.suggested_filename)
    pg.get_by_role("button", name="Continue").click()
    pg.wait_for_timeout(300)
    f = focused(pg)
    check("step 5: then the confirmation is asked for, the focus on its checkbox",
          pg.locator(".ui-field-error").all_inner_texts() == ["Confirm that you stored the recovery key offline."] and f["role"] == "checkbox",
          json.dumps(f))
    pg.keyboard.press("Space")
    pg.get_by_role("radio", name="USB disk").focus()
    pg.keyboard.press("ArrowDown")
    pg.wait_for_timeout(200)
    pg.get_by_role("button", name="Continue").click()
    pg.locator(".ui-field-error").first.wait_for()
    check("step 5: a network share needs its address", pg.locator(".ui-field-error").all_inner_texts() == ["Enter the share's address."])
    pg.locator("input[name=address]").fill("\\\\fail.office.local\\backups")
    pg.locator("input[name=user]").fill("backup-suveryn")
    pg.locator("input[name=password]").fill("secret")
    pg.get_by_role("button", name="Continue").click()
    pg.wait_for_timeout(300)
    check("step 5: and a tested connection", pg.locator("#share-test-status").inner_text() == "Test the connection before you continue.",
          pg.locator("#share-test-status").inner_text())
    pg.get_by_role("button", name="Test connection").click()
    pg.get_by_text("The appliance can't reach this share").wait_for()
    check("step 5: a failed test says why, in the status next to the button (read out)", True)
    pg.locator("input[name=address]").fill("\\\\nas.office.local\\backups")
    pg.get_by_role("button", name="Test connection").click()
    pg.get_by_text("Connected: the appliance can write to this share.").wait_for()
    pg.screenshot(path=OUT / "setup-5-share-en.png", full_page=True)
    pg.get_by_role("button", name="Continue").click()

    pg.get_by_role("heading", name="Review", level=1).wait_for()
    pg.screenshot(path=OUT / "setup-6-en.png", full_page=True)
    rows = pg.locator(".ui-row").all_inner_texts()
    check("step 6: the review shows every answer", any("Your own certificate" in r for r in rows) and any("Network share" in r for r in rows)
          and any("Sūveryn Enterprise" in r for r in rows), " | ".join(r.replace("\n", " ") for r in rows))
    pg.get_by_role("button", name="Edit Backups").click()
    pg.get_by_role("heading", name="Backups", level=1).wait_for()
    check("step 6: Edit opens the step with its key still downloaded and confirmed",
          pg.get_by_role("button", name="Download the recovery key").inner_text().strip() == "Downloaded"
          and pg.locator(".ui-checkbox[data-selected]").count() == 1)
    pg.get_by_text("USB disk", exact=True).click()
    pg.get_by_role("button", name="Continue").click()
    pg.get_by_role("heading", name="Review", level=1).wait_for()
    check("step 6: and its Continue returns to the review, with the change",
          any("USB disk" in r for r in pg.locator(".ui-row").all_inner_texts()))
    pg.get_by_role("button", name="Start provisioning").click()

    pg.get_by_role("heading", name="Setting up the sūveryn appliance", level=1).wait_for()
    pg.wait_for_timeout(2000)
    pg.screenshot(path=OUT / "setup-7-en.png", full_page=True)
    live = pg.locator("[aria-live=polite]").inner_text()
    check("provisioning: the step in progress is said in a live region, and the bar has a value",
          live != "" and pg.get_by_role("progressbar").get_attribute("aria-valuetext") is not None, live)
    pg.get_by_role("heading", name="Setup complete", level=1).wait_for(timeout=20000)
    pg.screenshot(path=OUT / "setup-8-en.png", full_page=True)
    link = pg.get_by_role("link", name="Open sūveryn")
    check("complete: every step done, the check passed, and Open sūveryn links to <name>.local",
          pg.locator(".ui-status[data-state=done]").count() == 5 and pg.get_by_text("Outgoing traffic limited").count() == 1
          and link.get_attribute("href") == "https://notary-brussels-01.local")
    done(pg, "setup, flow (en)")

    for variant, what in (("provisioning-fails", "a failed provisioning step"), ("check-fails", "a failed outgoing check")):
        pg = new_page(browser, f"setup, {variant}", **ctx)
        pg.variant = variant
        fill_to(pg, "review")
        pg.get_by_role("button", name="Start provisioning").click()
        if variant == "provisioning-fails":
            pg.get_by_role("alert").filter(has_text="Provisioning stopped").wait_for(timeout=10000)
            pg.screenshot(path=OUT / "setup-7-failed-en.png", full_page=True)
            check("provisioning: a failed step is said (alert) with where it stopped, and Try again",
                  pg.get_by_text('It stopped at "Sign-in and administrator"').count() == 1)
            pg.get_by_role("button", name="Try again").click()
            pg.get_by_role("heading", name="Setup complete", level=1).wait_for(timeout=20000)
            check("provisioning: Try again finishes it", True)
        else:
            pg.get_by_role("heading", name="Setup complete", level=1).wait_for(timeout=20000)
            pg.screenshot(path=OUT / "setup-8-check-failed-en.png", full_page=True)
            check("complete: a failed outgoing check is a warning saying what to do",
                  pg.get_by_text("This appliance can reach more than its approved list").count() == 1
                  and pg.locator(".ui-status[data-state=failed]").count() == 1)
        done(pg, f"setup, {what}")


def chat_model_menu(browser):
    """The chat's model menu on the library, with the keyboard."""
    pg = new_page(browser, "chat", viewport={"width": 1280, "height": 900}, locale="en-GB")
    pg.goto(f"{BASE}/")
    badge = pg.locator(".chip-model-button")
    badge.wait_for()
    badge.focus()
    pg.keyboard.press("Enter")
    menu = pg.get_by_role("menu", name="Model")
    menu.wait_for()
    items = pg.get_by_role("menuitemradio").all()
    checked = [i.get_attribute("aria-checked") for i in items]
    f = focused(pg)
    check("chat: Enter on the model badge opens a menu of radio items, the current model checked",
          len(items) == 3 and checked == ["true", "false", "false"], f"{checked} focus {json.dumps(f)}")
    pg.screenshot(path=OUT / "chat-model-menu.png")
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(200)
    f = focused(pg)
    check("chat: Escape closes it and the focus returns to the badge", menu.count() == 0 and "chip-model-button" in
          pg.evaluate("document.activeElement.className"), json.dumps(f))
    pg.keyboard.press("Enter"); menu.wait_for()
    pg.keyboard.press("ArrowDown"); pg.keyboard.press("Enter")
    pg.wait_for_timeout(300)
    check("chat: ArrowDown, Enter chooses the next model; the badge and the note follow",
          "Mistral" in badge.inner_text() and pg.get_by_text("Mistral").count() >= 1, badge.inner_text())
    done(pg, "chat, model menu")


def axe(browser):
    """axe-core on each screen (a separate page that may run the script; the CSP checks are above)."""
    out = {}
    c = browser.new_context(bypass_csp=True, viewport={"width": 1280, "height": 900}, locale="en-GB", accept_downloads=True)
    pg = c.new_page()

    def run(name):
        pg.add_script_tag(path=str(AXE))
        r = pg.evaluate("axe.run(document, {runOnly: ['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']})")
        out[name] = [{"id": v["id"], "impact": v["impact"], "nodes": len(v["nodes"]), "help": v["help"],
                      "targets": [n["target"] for n in v["nodes"]][:4]} for v in r["violations"]]
    pg.goto(f"{BASE}/setup.html"); pg.get_by_role("heading", name="Set up your sūveryn appliance").wait_for(); run("setup 0 welcome")
    pg.get_by_role("button", name="Get started").click(); pg.get_by_role("heading", name="Network", level=1).wait_for(); run("setup 1 network")
    pg.get_by_role("button", name="Continue").click(); pg.get_by_role("heading", name="Administrator account").wait_for()
    pg.get_by_role("button", name="Continue").click(); pg.locator(".ui-field-error").first.wait_for(); run("setup 2 with errors")
    pg.locator(".ui-select-button").click(); pg.get_by_role("listbox").wait_for(); run("setup language menu open")
    pg.keyboard.press("Escape")
    pg.locator("input[name=name]").fill("Filip Tack"); pg.locator("input[name=email]").fill("filip@firm.example")
    pg.locator("input[name=password]").fill("violet harbour lantern 47"); pg.locator("input[name=confirm]").fill("violet harbour lantern 47")
    pg.get_by_role("button", name="Continue").click(); pg.get_by_role("heading", name="Certificate", level=1).wait_for()
    pg.get_by_text("Use your own certificate", exact=True).click()
    pg.get_by_role("button", name="Continue").click(); pg.locator(".ui-field-error").first.wait_for(); run("setup 3 own, with errors")
    pg.get_by_text("Generate a self-signed certificate", exact=True).click()
    pg.get_by_role("button", name="Continue").click(); pg.get_by_role("heading", name="Support agreement").wait_for(); run("setup 4 support")
    pg.get_by_role("button", name="Continue").click(); pg.get_by_role("heading", name="Backups", level=1).wait_for()
    pg.get_by_role("button", name="Continue").click(); pg.locator(".ui-field-error").first.wait_for(); run("setup 5 with an error")
    pg.get_by_text("Network share", exact=True).click(); pg.wait_for_timeout(200); run("setup 5 network share")
    pg.get_by_text("USB disk", exact=True).click()
    pg.get_by_role("button", name="Download the recovery key").click(); pg.locator(".ui-checkbox").click()
    pg.get_by_role("button", name="Continue").click(); pg.get_by_role("heading", name="Review", level=1).wait_for(); run("setup 6 review")
    pg.get_by_role("button", name="Start provisioning").click(); pg.get_by_role("heading", name="Setting up the sūveryn appliance").wait_for()
    pg.wait_for_timeout(1600); run("setup 7 provisioning")
    pg.get_by_role("heading", name="Setup complete").wait_for(timeout=20000); run("setup 8 complete")
    pg.goto(f"{BASE}/"); pg.locator(".chip-model-button").click(); pg.get_by_role("menu").wait_for(); run("chat model menu open")
    c.close()
    return out


with sync_playwright() as p:
    b = p.chromium.launch()
    for f in (setup_keyboard, setup_languages, setup_flow, setup_phone, chat_model_menu):
        try:
            f(b)
        except Exception as e:  # noqa: BLE001
            check(f"{f.__name__} ran to the end", False, str(e).splitlines()[0])
    a = axe(b)
    b.close()

total = sum(len(v) for v in violations.values())
check("zero CSP violations on every page and in every flow", total == 0, json.dumps(violations))
check("no script errors", not errors, "; ".join(errors[:5]))
report = {"results": results, "csp_violations": violations, "errors": errors, "axe": a}
(OUT / "report.json").write_text(json.dumps(report, indent=2))
print(f"\n{sum(r['ok'] for r in results)}/{len(results)} passed; axe: " +
      ", ".join(f"{k}: {len(v)}" for k, v in a.items()))
