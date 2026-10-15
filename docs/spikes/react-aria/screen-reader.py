"""What a screen reader gets at each keyboard step: the focused element's accessible role, name,
description and states, from Chromium's accessibility tree (what screen readers read from). Not a
substitute for VoiceOver itself, which uses Safari's tree and decides the wording.

    python3 screen-reader.py <base-url>     # a build served by serve.py
"""
import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1]
def say(pg, cdp, label):
    tree = cdp.send("Accessibility.getFullAXTree")["nodes"]
    f = [n for n in tree if any(p["name"] == "focused" and p["value"]["value"] for p in n.get("properties", []))]
    if not f: print(f"{label:28} (nothing focused)"); return
    n = f[-1]; g = lambda k: (n.get(k) or {}).get("value", "")
    props = {p["name"]: p["value"].get("value") for p in n.get("properties", [])}
    states = [k if v is True else f"{k}={v}" for k, v in props.items() if k in ("checked","pressed","expanded","invalid","required","selected","haspopup","level","setsize","posinset") and v not in (False, "false", None)]
    desc = g("description")
    print(f"{label:28} {g('role')}: \"{g('name')}\"" + (f" | {', '.join(states)}" if states else "") + (f" | description: \"{desc}\"" if desc else ""))
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 900}); cdp = pg.context.new_cdp_session(pg)
    pg.goto(f"{BASE}/setup.html"); pg.get_by_role("button", name="Get started").click()
    pg.get_by_role("heading", name="Network").wait_for(); pg.wait_for_timeout(200)
    print("== Step 1")
    for i in range(4): pg.keyboard.press("Tab"); say(pg, cdp, f"Tab {i+1}")
    pg.keyboard.press("Shift+Tab"); pg.keyboard.press("Shift+Tab"); pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(150); say(pg, cdp, "Down arrow (access)")
    pg.keyboard.press("ArrowUp"); pg.wait_for_timeout(150); say(pg, cdp, "Up arrow")
    print("== Language menu"); pg.locator(".ui-select-button").focus(); say(pg, cdp, "on the menu")
    pg.keyboard.press("Enter"); pg.wait_for_timeout(300); say(pg, cdp, "Enter (opens)")
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(150); say(pg, cdp, "Down arrow")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300); say(pg, cdp, "Escape (closes)")
    print("== Step 2"); pg.get_by_role("button", name="Continue").click(); pg.get_by_role("heading", name="Administrator account").wait_for(); pg.wait_for_timeout(200)
    say(pg, cdp, "after Continue")
    for i in range(7): pg.keyboard.press("Tab"); say(pg, cdp, f"Tab {i+1}")
    pg.keyboard.press("Enter"); pg.wait_for_timeout(400); say(pg, cdp, "Continue, fields empty")
    pg.keyboard.press("Tab"); pg.keyboard.press("Tab"); say(pg, cdp, "Tab to Password")
    pg.keyboard.press("Tab"); pg.keyboard.press("Space"); pg.wait_for_timeout(150); say(pg, cdp, "Space on the eye")
    print("== Chat model menu"); pg.goto(f"{BASE}/"); b_ = pg.locator(".chip-model-button"); b_.wait_for(); b_.focus(); say(pg, cdp, "on the badge")
    pg.keyboard.press("Enter"); pg.wait_for_timeout(300); say(pg, cdp, "Enter (opens)")
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(150); say(pg, cdp, "Down arrow")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300); say(pg, cdp, "Escape")
    b.close()
