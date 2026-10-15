# The Content-Security-Policy and the browser code

How sūveryn's browser code (`packages/chat-ui`: the chat and the appliance's web setup) stays within the appliance's Content-Security-Policy, and what to do when a change or a library doesn't. Read this before adding a dependency to the UI, or when the build stops with a CSP error.

## The policy

The appliance's nginx sends this header with the UI and the gateway's answers (suveryn-appliance [`reverse-proxy/suveryn-csp.conf`](https://github.com/suveryn/suveryn-appliance/blob/main/reverse-proxy/suveryn-csp.conf)):

```
default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self';
connect-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self';
frame-ancestors 'none'
```

In plain words: the browser runs and applies only files that came from the appliance itself. Nothing written into the page while it runs, nothing from another host, no `eval`. The appliance's tests refuse `'unsafe-inline'`, `'unsafe-eval'`, `data:` and any other host in it.

**Why.** The appliance holds confidential documents, and the UI shows text that comes from them (passages, answers). If anything in that text ever got into the page as code or styling, this policy is what stops it from running. It also keeps the UI from contacting any other host. Every violation is reported by the browser, so **zero violations is a hard rule**: a clean console is what makes a real attack visible.

Keycloak's pages (sign-in, account) are not covered: Keycloak sends its own CSP, and nginx leaves it alone. The appliance's web setup (`setup.html`) must be served with this same policy (suveryn-tracker#37).

## Rules for the code

| Not allowed | Instead |
|---|---|
| `<script>` with code in it, `on…=` attributes in HTML | Code in modules, loaded as files (Vite does this) |
| `<style>` elements, and `style="…"` written in HTML | Rules in a `.css` file (`src/styles`, `src/ui/ui.css`, `src/setup/setup.css`) |
| `data:` URLs (inlined images or fonts) | Files; `assetsInlineLimit: 0` in `vite.config.ts` keeps Vite from inlining them |
| `eval`, `new Function`, string timers | Plain code |
| Anything from another host (fonts, icons, CDNs, analytics) | Bundled files, from suveryn-brand or `node_modules` |
| `dangerouslySetInnerHTML`, `innerHTML` with markup | React elements; answers are rendered element by element (`lib/answer.ts`) |

**Allowed:** styles set through the DOM. React's `style={{…}}` prop and `element.style.x = …` go through the CSSOM, which `style-src` doesn't restrict; React Aria positions its popovers this way. Only `<style>` elements and `style` attributes in markup are blocked.

`src/csp.test.ts` checks the source and the HTML entry pages for the things in the left column.

## Adding a library

Before adding a package that ends up in the browser bundle:

1. **Search it for runtime styling and code**: `createElement('style')` or `"style"`, `insertRule`, `adoptedStyleSheets`, `eval(`, `new Function`, `data:` URLs, and any URL to another host. Many UI libraries write a `<style>` element at run time (shadcn/ui's Radix does, through react-remove-scroll; it was ruled out for that, suveryn-tracker#44).
2. **Run it under the real policy**: build, serve the build with the appliance's headers and count violations in a real browser ([`docs/spikes/react-aria/`](spikes/react-aria/README.md): `serve.py` and `check.py`). Include a phone or iPhone/iPad emulation: libraries often take another code path there.
3. **If it writes styling at run time**, fix it with one of the patterns below, or don't use it.
4. Add it to the licence notices (`scripts/notices.mjs`).

## What to do when a library writes a `<style>`

In order of preference:

1. **Make it skip**: some libraries check whether their style is already there before writing it. Put a placeholder with that id in the page and carry the rule in our own CSS.
2. **Replace it at build time**: a small Vite plugin swaps the exact code that writes the `<style>` for code with the same effect that doesn't (an attribute on `<html>`, matched by a rule in our CSS). The match must be exact and **the build must fail when it doesn't match**, so that an update of the library can never quietly bring the `<style>` back.
3. **Don't use the library.**

**Never** loosen the policy for a library:

- not `'unsafe-inline'`: it would let any injected styling through;
- not a nonce: the UI is static files behind nginx, so the nonce would be a fixed value in every response, which protects nothing;
- not a hash (`'sha256-…'`): it would tie the appliance's nginx configuration (suveryn-appliance) to the exact bytes of a library in suveryn-core, and break, with violations again, on the next update of that library.

## The two exceptions we handle today (React Aria)

The component library (`packages/chat-ui/src/ui`) sits on React Aria Components, which writes two `<style>` elements of its own. Both are handled without touching the policy, and the measurements are in [`docs/spikes/react-aria/`](spikes/react-aria/README.md).

| React Aria writes | When | How we handle it | Where |
|---|---|---|---|
| `[data-react-aria-pressable] { touch-action: pan-x pan-y pinch-zoom }` (`usePress`) | First render of anything pressable: every page | Pattern 1. React Aria skips it when an element with id `react-aria-pressable-style` exists; `csp.ts` adds a `<meta>` with that id before anything renders, and `ui.css` carries the rule | `src/ui/csp.ts`, `src/ui/ui.css` |
| `* { overscroll-behavior: contain }` (`usePreventScroll`) | iPhone and iPad only, while a menu, select or dialog is open | Pattern 2. The Vite plugin `reactAriaCsp` replaces that code with an attribute `data-ui-prevent-scroll` on `<html>`, set and removed at the same moments; `ui.css` has `html[data-ui-prevent-scroll] * { overscroll-behavior: contain }` | `vite.config.ts`, `src/ui/ui.css` |

Each is checked:

- `src/csp.test.ts`: React Aria still checks the id `csp.ts` places and still writes the same pressable rule; `csp.ts` is still imported, and package.json has no `"sideEffects"`; and React Aria writes styling at run time in no place other than these two and `TokenField` (so an update that adds one fails the tests);
- `src/setup/setup.test.ts`: the plugin finds and replaces React Aria's code, fails on code it doesn't recognise, and `ui.css` has both rules;
- the browser check (`docs/spikes/react-aria/check.py`): zero violations on every page and flow, including iPhone emulation with a menu open, and no `<style>` element in the page.

**Not used: `TokenField`.** React Aria Components' `TokenField` adds a constructed stylesheet at run time. It isn't handled here, so screens don't use it (`src/csp.test.ts` checks); handle it with the patterns above first if it is ever needed.

**Keep `csp.ts` imported for its effect** (`import "./csp"` in `src/ui/index.ts`). Marking the package side-effect free (`"sideEffects"` in package.json) made the bundler drop it, and the violation came back; the browser check caught that.

### When the build stops after a React Aria update

The error reads: `React Aria's inline <style> for preventing scroll changed; update reactAriaCsp in vite.config.ts`. It means React Aria changed the code the plugin replaces. Then:

1. Open `node_modules/react-aria/dist/private/overlays/usePreventScroll.mjs` and find where it now creates the `<style>`.
2. Update `PREVENT_SCROLL_STYLE` in `vite.config.ts` to the new code exactly, and the replacement if the rule or its timing changed (it must still set the attribute when the style would be added and remove it when the style would be removed). Update the rule in `ui.css` if React Aria's rule changed.
3. Check whether React Aria now writes any other `<style>` (step 1 of *Adding a library*). `npm test` tells you if the pressable one changed its id or rule.
4. Run `npm test` and the browser check; both must pass with zero violations.

If React Aria ever offers a supported way to turn these styles off, use that and remove both workarounds.

## Checking

```bash
cd packages/chat-ui
npm test                    # source rules (src/csp.test.ts) and the React Aria replacement
npm run build               # fails if the replacement no longer matches
# the browser check, with the appliance's real headers: docs/spikes/react-aria/README.md, "Running the checks again"
```
