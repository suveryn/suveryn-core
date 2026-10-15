# Spike: React Aria Components under the strict CSP

suveryn-tracker#44, October 2026. The question: can React Aria Components (Adobe, Apache-2.0), styled with the brand tokens, be the chat UI's component foundation, with **zero CSP violations** under the appliance's real policy? Its first user is the appliance's web setup (#37).

How this is handled from now on, for every change and library: [docs/content-security-policy.md](../../content-security-policy.md).

**Result: it holds.** Out of the box React Aria breaks the CSP (one violation on every page, a second on iPhone and iPad), but both are fixed without loosening the policy, and with the fixes every flow below runs with zero violations, no script errors and no axe findings. Recommendation: adopt it, finish the web setup on it (#37), and move the remaining hand-built menus over.

## What was built

In `packages/chat-ui` (see its README, sections *Components* and *The web setup*):

- **`src/ui/`, the component library**: Button, TextField, PasswordField, Form, RadioCards, RadioList, Select, MenuButton, and Card, Steps, Note, Facts, Chips. Styled in `ui.css` from the brand tokens through React Aria's `data-*` states; no inline styles.
- **`setup.html` and `src/setup/`, the web setup's own entry**: steps 1 (Network) and 2 (Administrator account) from the approved design, in English, Dutch and French. No sign-in code and nothing from the chat.
- **The chat's model menu** moved onto the library (`MenuButton`). The hand-built version had no arrow-key navigation.

## Measurements

Run against a production build served with the appliance's real headers (`suveryn-appliance/reverse-proxy/suveryn-csp.conf` and `suveryn-headers.conf`), in Chromium, with [`serve.py`](serve.py) and [`check.py`](check.py) in this folder.

### CSP violations

| Build | Violations |
|---|---|
| React Aria as it comes | 1 on every page load (`style-src-elem`, inline `<style>`), +1 on iPhone/iPad each time a menu opens |
| With the two fixes | **0** in every flow below (desktop, keyboard, three languages, iPhone emulation, chat) |

The two `<style>` elements React Aria writes, and the fixes:

1. **Pressable elements** (`usePress`, on first render): a `touch-action` rule. React Aria skips it when an element with its id is already in the page, so `src/ui/csp.ts` adds a placeholder, and `ui.css` carries the rule.
2. **Scroll lock on iPhone and iPad** (`usePreventScroll`, while a menu or dialog is open): `overscroll-behavior: contain`. A build step in `vite.config.ts` replaces the `<style>` with an attribute on `<html>`, matched by a rule in `ui.css`. The match is exact, so a React Aria update that changes this code fails the build instead of quietly bringing the `<style>` back (a unit test checks both directions).

A nonce was not an option: the UI is static files behind nginx, and a fixed nonce would weaken the policy for nothing. Positioning styles that React Aria sets through the DOM (`element.style`) are allowed by `style-src 'self'`.

### Bundle size (first load, JavaScript and CSS, gzip)

| | Before | After |
|---|---|---|
| Chat | 101 kB | 158 kB (+57 kB) |
| Web setup | n/a | 133 kB (React and React DOM 60 kB, React Aria and the library about 70 kB) |

Fonts are unchanged and not counted. The +57 kB is mostly React Aria's core (press, focus, overlays, collections, internationalisation), paid once: the first menu brings it in, further components add little. On an office LAN it is a few tens of milliseconds. Two things were tried:

- `@react-aria/optimize-locales-plugin` keeps React Aria's own strings for English, Dutch and French only: about 9 kB raw saved, kept.
- `"sideEffects"` in package.json, to let the chat drop the setup's components: about 6 kB saved, but it also dropped `csp.ts` and brought the violation back (the check caught it). Not kept.

### Keyboard, screen-reader semantics, languages, phone

All 26 checks in `check.py` pass:

- **Step 1**: Tab goes language menu, internet access, outgoing connections, Continue (one stop per radio group). The arrow keys change the choice; choosing Air-gapped removes the outgoing options and Connected brings them back.
- **Step 2**: the focus moves to the new step's heading. No error while typing or leaving a field. Continue shows every error under its field, tied to it with `aria-describedby`, and moves the focus to the first field in error. Changing a field and leaving it clears its error. The show/hide toggle is a toggle button (`aria-pressed`) after the field. The appliance's name in the password is refused; a good account continues.
- **Language menu**: Enter opens a listbox (English, Nederlands, Français, each in its own language); arrow keys and Enter switch; the page follows at once (`lang="nl-BE"`, the tab title) and the focus returns to the menu. Errors in Dutch and French. Answers survive a language switch.
- **Phone (375 px, iPhone emulation, French, the longest copy)**: no sideways scrolling on either step, also with errors shown. The scroll lock works through the attribute, with no `<style>` element.
- **Chat**: Enter on the model badge opens a menu of radio items with the current model checked; Escape closes it and returns the focus; arrow keys and Enter choose another model.
- **axe-core** (WCAG 2.2 A/AA and best practices) on step 1, step 2 with errors, the open language menu and the open model menu: **no findings**.

### Next to the Keycloak login

Keycloak 26.8.0 with the sūveryn theme (built from `suveryn-appliance/keycloak/theme`), the login page beside setup step 2 at 1280 px: one product. Same colours, fonts (Space Grotesk 24/600 headings, Inter 15), card surface, border and 14 px corners, accent button, focus ring (border `#0F8A82` with the 3 px `rgba(58,212,202,.15)` glow, measured on both), the language menu's icon and place in the card.

Differences to settle (not caused by React Aria):

| | Keycloak login | Web setup (design) |
|---|---|---|
| Card width | 400 px | 560 px (by design: more content) |
| Lockup | logo 48 px high, 251 px wide | icon 44 px, wordmark 32 px, 196 px wide |
| Field height | 35 px (PatternFly padding) | 45 px |
| Button height | 43 px | 40 px |
| Language button | 32 px, filled caret | 37 px, chevron |

Suggestion: put the shared base rules (focus colours, field and button sizes, card, lockup size) in suveryn-brand as tokens, so the Keycloak theme and `ui.css` both take them from there. The focus colours aren't brand tokens yet; they are repeated in both for now.

## Findings to keep

- **React 19 form actions and React Aria fields**: given a form's `action`, React resets the form after each submit, and React Aria's fields follow the reset, so every answer was wiped when Continue found an error. The library's `Form` starts the action from `onSubmit` instead (`useActionState` with `startTransition`).
- **Don't use React Aria's built-in validation** (`isRequired`, the browser's `type="email"` check): its messages come from the browser, in its language. The screens check their own fields and the errors are in the interface language.
- **Server errors clear when a field is left**, not on every keystroke (React Aria's behaviour). Fine for the design.
- **An error shown before a language switch stays in the old language** until the next Continue. Small; fixable by keeping error keys rather than strings.
- **Locales**: React Aria falls back from en-GB, nl-BE and fr-BE to its en-US, nl-NL and fr-FR strings.

## Not covered by this spike

- **VoiceOver** (and Safari's own engine): needs a Mac. Script below.
- Components not built yet: Tabs, Table, Toast, Dialog, file upload, and a router. React Aria has all but the router; the CSP fixes above cover dialogs too (same scroll lock).
- The common-password check is a short list; the real one needs a leaked-password list on the appliance, shared with Keycloak's `passwordBlacklist` (#37).
- Native-speaker review of the Dutch and French setup text.

## VoiceOver check (about 10 minutes, on a Mac)

Open the setup in Safari: `npm run dev` in `packages/chat-ui`, then http://localhost:5173/setup.html (example network settings), or the preview link from the spike. Turn VoiceOver on with Cmd+F5. Move with Tab, and read with VO+Right Arrow (VO is Control+Option).

1. **Language menu**: Tab to it. Expect "English, Language, pop-up button" (or "menu button"). Press VO+Space, then Down Arrow: "Nederlands". Enter: the page is in Dutch and VoiceOver now reads Dutch text with a Dutch voice.
2. **Internet access**: Tab. Expect "Connected, radio button, selected, 1 of 2" plus its description. Down Arrow: "Air-gapped … 2 of 2"; the outgoing options disappear. Up Arrow back.
3. **Outgoing connections**: Tab. Expect "Approved destinations only (recommended), radio button, selected, 1 of 2".
4. **Continue**: Enter. Expect VoiceOver to read "Administrator account, heading level 1".
5. **Fields**: Tab through. Each field's label is read; the email field also reads "Used to sign in. It stays on this appliance." The eye button: "Show password, toggle button, not selected"; VO+Space shows the password.
6. **Errors**: Tab to Continue, press Enter with the fields empty. Expect the focus on Full name, read as "Full name, invalid data, Enter your full name." Tab to Password: its error is read too.
7. **Phone**: optionally the same on an iPhone with VoiceOver (Settings > Accessibility), swiping right to move.

Note anything read wrong, twice, or not at all. That decides whether a fix is needed before the library is adopted.

## Running the checks again

```bash
cd packages/chat-ui && npm run build
python3 ../../docs/spikes/react-aria/serve.py dist 8765 <suveryn-appliance>/reverse-proxy &
AXE_JS=<axe-core>/axe.min.js python3 ../../docs/spikes/react-aria/check.py http://127.0.0.1:8765 /tmp/spike
```

Needs Python Playwright with Chromium, and axe-core 4.10 (`npm install axe-core@4.10.3` anywhere). Screenshots and `report.json` go to the output folder.
