# suveryn-core

The engine of sūveryn: private AI for work that can't leave the premises. This repository holds the harness around the model, the API gateway, document ingestion and retrieval, the chat UI, and the official playbooks (deed intake, the one public reference playbook; the certified packs are in the private suveryn-packs repository and load from `SUVERYN_PACKS_DIR`). AGPL-3.0-or-later. The runtime services (PostgreSQL, Keycloak, llama-server) are installed by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance), not here.

Start with the private [suveryn-handbook](https://github.com/suveryn/suveryn-handbook/blob/main/context/development-context.md#start-here), its *Start here*: the design principles, the project's words, and how a change reaches `main`. Its synthesis says what sūveryn is, what is decided and what is open. Then:

| To understand | Read |
|---|---|
| What exists, data flow, where confidential data lives, invariants, decisions with evidence, known limitations, the review checklist | [docs/architecture.md](docs/architecture.md) |
| The grounded prompt, injection handling, server-side calculation, citation checks | [docs/harness.md](docs/harness.md); what rules check, where each language's words live, and what is proposed for meaning: [docs/design/answer-checks.md](docs/design/answer-checks.md) |
| The chat interface, screen by screen; sources, playbook messages, administration | [docs/design/chat-ui.md](docs/design/chat-ui.md), [docs/design/admin.md](docs/design/admin.md) |
| Cases, playbooks, the platform's order of work | [docs/design/cases.md](docs/design/cases.md), [docs/design/playbooks.md](docs/design/playbooks.md), [docs/design/platform.md](docs/design/platform.md); templates, proposed: [docs/design/templates.md](docs/design/templates.md) |
| Languages and copy rules | [docs/translations.md](docs/translations.md) |
| What the server says when something goes wrong or needs checking: codes, their four kinds, the registry | [docs/design/messages.md](docs/design/messages.md) |
| Each package | its `README.md` under `packages/` |

## Before you start

<!-- shared: copied from suveryn-handbook/context/claude-md-shared.md; change it there, never here -->

1. **Read the handbook's [*Start here*](https://github.com/suveryn/suveryn-handbook/blob/main/context/development-context.md#start-here)** before any work: the design principles, the project's words, how a change reaches `main`. If you can't open it, stop and say so. In a long session, read it again when the conversation has been summarised.
2. **One issue, one branch, one PR.** The change has an issue in suveryn-tracker and the branch is named for it. No branch is built on an unmerged branch. A coding agent never pushes: it delivers its branch into the founder's local clone without switching that clone's branch, and only the founder pushes and merges.
3. **Before you ask for a merge**, say which design principle the change bends, if any, and why. A bent principle needs the founder's decision in the handbook before the merge.

<!-- /shared -->

## Rules

The handbook's [design principles](https://github.com/suveryn/suveryn-handbook/blob/main/context/development-context.md#the-design-principles) and its *How a change reaches `main`* hold here and are not repeated. These are the places in this code where they live:

- **The model:** everything that goes to it or checks what comes back passes through `suveryn_harness` (the prompt, citations, calculations, the thinking fallback); no second path, no `eval`, nothing tuned to one model.
- **Sources:** only uploaded documents are sources; every document records its `origin`, and sūveryn never cites its own output.
- **Offline:** no CDN asset in the chat UI; FastAPI's `/docs` stays off by default.
- **Confidential data:** fictional test documents only (`trap_deed.py`); the access log records kinds, ids and pages, never text.
- **All or nothing:** several writes to one store go in `PgStore.transaction()`; a change across stores is made of steps that are safe to repeat (`delete_case_everywhere`).
- **Failures and warnings:** a code of the registry (`suveryn_harness/messages.json`), never a sentence: `raise Problem(code, …)` for one that takes the answer's place, `message(code, …)` for one inside an answer or stored; the gateway answers Problem Details, anything unplanned gets a reference, and the page words the code in the reader's language (`lib/messages.ts`, `i18n/`; the appliance's web setup says the `setup` area's codes, worded in `setup/i18n/`). A code is never renamed or reused. [docs/design/messages.md](docs/design/messages.md); the plain refusals left are counted and only go down (`test_problems.py`).
- **Words at the edge:** the server stores what happened (a turn's kind, step, facts, values), never a sentence for the screen; the screen words it in the viewer's language, and the server writes words only into documents, in their document language. Dates, numbers, amounts and lists are formatted in one module for the current locale. The handbook's [decision of 12 November](https://github.com/suveryn/suveryn-handbook/blob/main/decisions/2026-11-12-meaning-on-the-server.md); the code catches up issue by issue (suveryn-tracker#126 to #131).
- **Screens:** built from the kit in `packages/chat-ui/src/ui/` (React Aria underneath); product components never import React Aria directly, and icons come through the kit. The end-to-end scenarios find every control by its role and name. A screen follows its design board (the handbook's [decision of 6 November](https://github.com/suveryn/suveryn-handbook/blob/main/decisions/2026-11-06-design-to-code.md)); a change to it updates its preview (`packages/chat-ui/src/preview/`, the README's *Screen previews*) and, once the board agrees, its baseline screenshot (the label *remake the baselines* on the PR; CI commits it) in the same PR; CI fails a screen that moved without one.
- **Brand:** copied from suveryn-brand at a pinned commit (`brand-lock.json`, `npm run brand:sync`); colours are `oklch(from var(--token) …)`, text sizes the brand's named styles, and spacing is on the brand's 4 px grid (`--space-*` tokens where one exists; the guidelines' *Spacing: a 4 px grid*). Tests fail on a new hex, a font-size literal, or a spacing value off the grid (`src/styles/grid.test.ts`).
- **Copy and languages:** [docs/translations.md](docs/translations.md) says where every string lives; a language file holds text, never code: a sentence with a value or a plural is ICU MessageFormat (`m(…)`, `src/i18n/message.ts`); `src/i18n/rules.ts` checks each against the brand's wording rules, and a missing language fails the build. Words a package reads or writes itself follow the same rule: the harness's (numbers in words, months, abbreviations), the rag's and the gateway's are in each package's `lang/<lang>.json`, none in the code, and a test fails on one in any package (`harness/tests/test_language.py`; the chat UI's `src/i18n/words-in-code.test.ts`).
- **One place:** each thing is known in one place: one reader of amounts and dates (`values.py`), one marking, one list of languages. Where the browser must know what the server knows, one shared case file tests both. Code nothing uses is removed.

## Verify

```bash
uv sync --all-packages --dev && uv run pytest -q          # Python (ruff: uvx ruff check --select F,E9 .)
cd packages/chat-ui && npm ci && npm run typecheck && npm test && npm run build
```

The end-to-end suite ([e2e/README.md](e2e/README.md)) runs on every PR in CI; locally, `uv run python e2e/stack.py up` then `uv run pytest e2e/tests`. A change to a screen or a flow that a scenario walks through changes the scenario in the same PR.

Before asking for a merge, walk the review checklist in [architecture.md §8](docs/architecture.md). The appliance pins this repository by commit; after a merge, the pin moves in its own PR there.
