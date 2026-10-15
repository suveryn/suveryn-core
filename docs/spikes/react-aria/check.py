"""The spike's measurements (suveryn-tracker#44), against a build served with the appliance's real CSP
(serve.py). Prints each check, writes report.json and screenshots.

    python3 check.py <base-url> <out-dir>        # needs Python Playwright with Chromium, and axe-core:
    AXE_JS=<path to axe-core/axe.min.js>          # npm install axe-core@4.10.3 in any folder
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
    pg.get_by_role("heading", name="Network", level=1).wait_for()
    pg.screenshot(path=OUT / "setup-1-en.png", full_page=True)

    order = []
    for _ in range(4):
        pg.keyboard.press("Tab")
        order.append(focused(pg))
    names = [f"{o['role']}:{o['name']}" for o in order]
    check("step 1: Tab goes language menu, internet access, outgoing connections, Continue",
          [o["role"] for o in order] == ["button", "radio", "radio", "submit"] and order[1]["name"].startswith("Connected")
          and order[2]["name"].startswith("Approved"), " → ".join(names))

    pg.keyboard.press("Shift+Tab"); pg.keyboard.press("Shift+Tab")  # back to Connected
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
    pg.keyboard.press("Tab"); pg.keyboard.press("Enter")

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
    pg.get_by_test_id("spike-end").wait_for()
    check("step 2: a good account continues", True)
    done(pg, "setup, keyboard (en)")


def setup_languages(browser):
    """The language menu with the keyboard, then Dutch and French errors."""
    pg = new_page(browser, "setup, languages", viewport={"width": 1280, "height": 900}, locale="en-GB")
    pg.goto(f"{BASE}/setup.html")
    pg.get_by_role("heading", name="Network", level=1).wait_for()
    pg.keyboard.press("Tab")
    pg.keyboard.press("Enter")
    lb = pg.get_by_role("listbox")
    lb.wait_for()
    opts = pg.get_by_role("option").all_inner_texts()
    pg.keyboard.press("ArrowDown"); pg.keyboard.press("Enter")
    pg.get_by_role("heading", name="Netwerk", level=1).wait_for()
    pg.wait_for_timeout(300)
    f = focused(pg)
    check("language menu: Enter opens a listbox (English, Nederlands, Français); ArrowDown, Enter switches to Dutch",
          opts == ["English", "Nederlands", "Français"], str(opts))
    check("language menu: the page follows at once (lang nl-BE, title) and the focus returns to the menu",
          pg.evaluate("document.documentElement.lang") == "nl-BE" and pg.title().endswith("Netwerk")
          and f["role"] == "button", f"{pg.evaluate('document.documentElement.lang')} {pg.title()} {json.dumps(f)}")
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


def setup_phone(browser):
    """Phone width (375 px), as an iPhone: no sideways scrolling; React Aria's scroll lock without a <style>."""
    pg = new_page(browser, "setup, phone", viewport={"width": 375, "height": 812}, user_agent=IPHONE_UA,
                  is_mobile=True, has_touch=True, device_scale_factor=2, locale="fr-BE")
    pg.goto(f"{BASE}/setup.html")
    pg.get_by_role("heading", name="Réseau", level=1).wait_for()
    w = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    check("phone: step 1 in French fits 375 px (no sideways scrolling)", w[0] <= w[1], str(w))
    pg.screenshot(path=OUT / "setup-1-fr-phone.png", full_page=True)
    pg.locator(".ui-select-button").tap()
    pg.get_by_role("listbox").wait_for()
    attr = pg.evaluate("document.documentElement.hasAttribute('data-ui-prevent-scroll')")
    styles = pg.evaluate("document.querySelectorAll('style').length")
    check("iPhone: an open menu locks scrolling through the attribute, with no <style> element", attr and styles == 0,
          f"attribute {attr}, <style> elements {styles}")
    pg.screenshot(path=OUT / "setup-1-fr-phone-menu.png")
    pg.get_by_role("option", name="Français").tap()
    pg.wait_for_timeout(300)
    check("iPhone: closing the menu removes the attribute",
          not pg.evaluate("document.documentElement.hasAttribute('data-ui-prevent-scroll')"))
    pg.get_by_role("button", name="Continuer").tap()
    pg.get_by_role("heading", name="Compte administrateur").wait_for()
    pg.get_by_role("button", name="Continuer").tap()
    pg.locator(".ui-field-error").first.wait_for()
    w = pg.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    check("phone: step 2 with its errors in French fits 375 px", w[0] <= w[1], str(w))
    pg.screenshot(path=OUT / "setup-2-errors-fr-phone.png", full_page=True)
    done(pg, "setup, phone (iPhone, fr)")


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
    c = browser.new_context(bypass_csp=True, viewport={"width": 1280, "height": 900}, locale="en-GB")
    pg = c.new_page()

    def run(name):
        pg.add_script_tag(path=str(AXE))
        r = pg.evaluate("axe.run(document, {runOnly: ['wcag2a','wcag2aa','wcag21aa','wcag22aa','best-practice']})")
        out[name] = [{"id": v["id"], "impact": v["impact"], "nodes": len(v["nodes"]), "help": v["help"],
                      "targets": [n["target"] for n in v["nodes"]][:4]} for v in r["violations"]]
    pg.goto(f"{BASE}/setup.html"); pg.get_by_role("heading", name="Network").wait_for(); run("setup step 1")
    pg.get_by_role("button", name="Continue").click(); pg.get_by_role("heading", name="Administrator account").wait_for()
    pg.get_by_role("button", name="Continue").click(); pg.locator(".ui-field-error").first.wait_for(); run("setup step 2 with errors")
    pg.locator(".ui-select-button").click(); pg.get_by_role("listbox").wait_for(); run("setup language menu open")
    pg.goto(f"{BASE}/"); pg.locator(".chip-model-button").click(); pg.get_by_role("menu").wait_for(); run("chat model menu open")
    c.close()
    return out


with sync_playwright() as p:
    b = p.chromium.launch()
    for f in (setup_keyboard, setup_languages, setup_phone, chat_model_menu):
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
