# Languages and translations

sūveryn speaks English, Dutch and French: the chat, the web setup, the sign-in pages, the console
installer and the playbooks. This page says where every piece of text lives, the rules all of it
follows, and what to do to add a language. The rule of thumb: **one list of languages, one file per
language per place, and a test that fails when a place is missing one.**

## Where the text lives

| What | Where | One file per language | Checked by |
|---|---|---|---|
| The list of languages (UI) | `packages/chat-ui/src/i18n/languages.ts`: `LANGS`, `LANGUAGE_NAMES`, `LOCALES`; the current choice | (the list itself) | TypeScript: every table is a `Record<Lang, …>` |
| The list of languages (server) | `suveryn_playbooks.LANGUAGES` (`packages/playbooks`), used by the gateway's sign-in | (the list itself) | `packages/playbooks/tests/test_content.py`: same as the UI's list and the realm's `supportedLocales` |
| The chat | `packages/chat-ui/src/i18n/<lang>.ts`, registered in `i18n/index.ts` | yes | TypeScript (every key of `en.ts`); `i18n.test.ts` (the copy rules) |
| The web setup | `packages/chat-ui/src/setup/i18n/<lang>.ts`, registered in `setup/i18n/index.ts` | yes | TypeScript; `setup.test.ts` (the copy rules) |
| Playbooks: title, one line, fact labels | `packages/playbooks/src/suveryn_playbooks/<pack>/text/<lang>.json`, one file per pack | yes | `test_content.py`: every playbook has every language, every fact a label |
| The sign-in, account and email pages | suveryn-appliance `keycloak/theme/src/suveryn/<theme>/messages/messages_<lang>.properties`; the realm's `supportedLocales` in `packages/api-gateway/keycloak/suveryn-realm.json` | yes | the theme's `test_theme.py`; `test_content.py` (the realm) |
| The console installer | suveryn-appliance `image/mkosi/mkosi.extra/usr/lib/suveryn/installer-text.json`, every key with each language beside it; the language menu in `installer-ui` | no: one file, languages side by side | the installer's tests |
| The website | suveryn-website, its own workflow (project doc `website-workflow`) | per page | the website's checks |
| Answers | none: the model answers in the language of the question | | |

Code, comments, identifiers and test data are in **English** only. A language's words appear only in
the files above. Messages from the server (error details) are English; the UI says what happened in
its own words by HTTP status (`api.ts`, `responseError`).

## The rules every language follows

The brand voice (suveryn-brand, "Tone of voice", "Wording and spelling"), checked for the chat and the
web setup by `packages/chat-ui/src/i18n/rules.ts` (`copyProblems`):

- nothing empty;
- "sūveryn" in lower case, also mid-sentence; a capital only where it opens a sentence or a label;
  "Sūveryn Labs" is the company;
- formal address: Dutch u and uw, never je, jij, jouw or jullie; French vous, never tu;
- no em dashes;
- the tagline stays in English: "AI for work that can't leave the premises".

A string that exists already is reused as it is; a new screen doesn't coin a second wording for the
same thing.

## Adding a language

Say German (`de`). In this order:

1. **The lists.** Add `"de"` to `LANGS`, `LANGUAGE_NAMES` (`"Deutsch"`) and `LOCALES` (`"de-BE"`) in
   `languages.ts`; to `LANGUAGES` in `suveryn_playbooks`; to `supportedLocales` in the realm file.
   From here the build and the tests say what is missing.
2. **The chat.** Copy `i18n/en.ts` to `i18n/de.ts`, translate, add it to `TABLES` in `i18n/index.ts`.
3. **The web setup.** The same with `setup/i18n/de.ts` and `TEXT` in `setup/i18n/index.ts`.
4. **The playbooks.** One `text/de.json` per pack.
5. **Formal address.** If the language has a formal and an informal "you", add its informal forms to
   `copyProblems` in `rules.ts`.
6. **The appliance** (suveryn-appliance): `messages_de.properties` for each Keycloak theme (login,
   account, email); a `"de"` beside every key of `installer-text.json` and the console's language menu.
   Its tests name the three languages themselves (`keycloak/theme/tests/test_theme.py`,
   `image/mkosi/test/test_installer_ui.py`): add `de` there too.
7. **The website**, if it should speak it too.
8. **A native speaker reviews** every new file before it ships: the translations are machine-drafted
   until then.

Nothing else changes: the sign-in page, dates and numbers follow the list.
