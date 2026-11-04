# suveryn-core

The engine of sūveryn: private AI for work that can't leave the premises. This repository holds the harness around the model, the API gateway, document ingestion and retrieval, the chat UI, and the official playbooks (deed intake, the one public reference playbook; the certified packs are in the private suveryn-packs repository and load from `SUVERYN_PACKS_DIR`). AGPL-3.0-or-later. The runtime services (PostgreSQL, Keycloak, llama-server) are installed by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance), not here.

Start with the private [suveryn-handbook](https://github.com/suveryn/suveryn-handbook/blob/main/context/development-context.md#start-here), its *Start here*: the design principles, the project's words, and how a change reaches `main`. Its synthesis says what sūveryn is, what is decided and what is open. Then:

| To understand | Read |
|---|---|
| What exists, data flow, where confidential data lives, invariants, decisions with evidence, known limitations, the review checklist | [docs/architecture.md](docs/architecture.md) |
| The grounded prompt, injection handling, server-side calculation, citation checks | [docs/harness.md](docs/harness.md) |
| The chat interface, screen by screen; sources, playbook messages, administration | [docs/design/chat-ui.md](docs/design/chat-ui.md), [docs/design/admin.md](docs/design/admin.md) |
| Cases, playbooks, the platform's order of work | [docs/design/cases.md](docs/design/cases.md), [docs/design/playbooks.md](docs/design/playbooks.md), [docs/design/platform.md](docs/design/platform.md); templates, proposed: [docs/design/templates.md](docs/design/templates.md) |
| Languages and copy rules | [docs/translations.md](docs/translations.md) |
| Each package | its `README.md` under `packages/` |

## Rules

The handbook's [design principles](https://github.com/suveryn/suveryn-handbook/blob/main/context/development-context.md#the-design-principles) and its *How a change reaches `main`* hold here and are not repeated. These are the places in this code where they live:

- **The model:** everything that goes to it or checks what comes back passes through `suveryn_harness` (the prompt, citations, calculations, the thinking fallback); no second path, no `eval`, nothing tuned to one model.
- **Sources:** only uploaded documents are sources; every document records its `origin`, and sūveryn never cites its own output.
- **Offline:** no CDN asset in the chat UI; FastAPI's `/docs` stays off by default.
- **Confidential data:** fictional test documents only (`trap_deed.py`); the access log records kinds, ids and pages, never text.
- **All or nothing:** several writes to one store go in `PgStore.transaction()`; a change across stores is made of steps that are safe to repeat (`delete_case_everywhere`).
- **Failures:** the server sends a failure as a code, and the page words it in the reader's language (`failureWords`, `i18n/`).
- **Screens:** built from the kit in `packages/chat-ui/src/ui/` (React Aria underneath); product components never import React Aria directly, and icons come through the kit. The end-to-end scenarios find every control by its role and name.
- **Brand:** copied from suveryn-brand at a pinned commit (`brand-lock.json`, `npm run brand:sync`); colours are `oklch(from var(--token) …)`, text sizes the brand's named styles. Tests fail on a new hex or a pixel literal.
- **Copy and languages:** [docs/translations.md](docs/translations.md) says where every string lives; `src/i18n/rules.ts` checks each against the brand's wording rules, and a missing language fails the build.

## Verify

```bash
uv sync --all-packages --dev && uv run pytest -q          # Python (ruff: uvx ruff check --select F,E9 .)
cd packages/chat-ui && npm ci && npm run typecheck && npm test && npm run build
```

The end-to-end suite ([e2e/README.md](e2e/README.md)) runs on every PR in CI; locally, `uv run python e2e/stack.py up` then `uv run pytest e2e/tests`. A change to a screen or a flow that a scenario walks through changes the scenario in the same PR.

Before asking for a merge, walk the review checklist in [architecture.md §8](docs/architecture.md). The appliance pins this repository by commit; after a merge, the pin moves in its own PR there.
