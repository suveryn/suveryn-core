# suveryn-core

The engine of sūveryn: private AI for work that can't leave the premises. This repository holds the harness around the model, the API gateway, document ingestion and retrieval, the chat UI, and the official playbooks. AGPL-3.0-or-later. The runtime services (PostgreSQL, Keycloak, llama-server) are installed by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance), not here.

Start with the private [suveryn-handbook](https://github.com/suveryn/suveryn-handbook) (`context/development-context.md`) for what sūveryn is, what is decided and what is open. Then:

| To understand | Read |
|---|---|
| What exists, data flow, where confidential data lives, invariants, decisions with evidence, known limitations, the review checklist | [docs/architecture.md](docs/architecture.md) |
| The grounded prompt, injection handling, server-side calculation, citation checks | [docs/harness.md](docs/harness.md) |
| The chat interface, screen by screen; sources, playbook messages, administration | [docs/design/chat-ui.md](docs/design/chat-ui.md), [docs/design/admin.md](docs/design/admin.md) |
| Cases, playbooks, the platform's order of work | [docs/design/cases.md](docs/design/cases.md), [docs/design/playbooks.md](docs/design/playbooks.md), [docs/design/platform.md](docs/design/platform.md) |
| Languages and copy rules | [docs/translations.md](docs/translations.md) |
| Each package | its `README.md` under `packages/` |

## Rules

- **A spec changes in the same PR as the code.** If a change makes a sentence in `docs/` false, the PR fixes the sentence. Decisions are recorded where they will be read: the area's design note, or the handbook for cross-repository and commercial ones.
- **One branch and PR per change, named for its tracker issue** ([suveryn-tracker](https://github.com/suveryn/suveryn-tracker/issues), `suveryn-tracker#n`). Merge only when Filip says so. Never push to `main`; never change repository settings, secrets or CI.
- **Document text is data, never instructions.** Everything that goes to the model passes through `suveryn_harness`; no second path. Every figure in an answer is in a passage or is a server calculation; no model arithmetic, no `eval`.
- **Only uploaded documents are sources.** Sūveryn never cites its own output; every document records its origin.
- **Nothing depends on the network at runtime**: no CDN, no public identity provider, no time server. FastAPI's `/docs` stays off by default for that reason.
- **Confidential data never appears in logs, tests, chats or PRs.** Fictional documents only (`trap_deed.py`); the audit log records kinds, ids and pages, never text.
- **Every screen is built from the kit in `packages/chat-ui/src/ui/`** (React Aria underneath). Product components never import React Aria directly; the kit grows when a screen needs something.
- **Brand comes from suveryn-brand at a pinned commit** (`brand-lock.json`, `npm run brand:sync`). Colours are `oklch(from var(--token) …)`, never a new hex; text sizes are the brand's named styles, never a pixel literal. Tests fail on both.
- **Copy:** UK English; formal Dutch (*u*) and French (*vous*); "sūveryn" lower case except at a sentence start or as the company; no em dashes; short. `src/i18n/rules.ts` enforces it on every string, and a missing language fails the build. Code, comments and test data are English.

## Verify

```bash
uv sync --all-packages --dev && uv run pytest -q          # Python (ruff: uvx ruff check --select F,E9 .)
cd packages/chat-ui && npm ci && npm run typecheck && npm test && npm run build
```

Before asking for a merge, walk the review checklist in [architecture.md §8](docs/architecture.md). The appliance pins this repository by commit; after a merge, the pin moves in its own PR there.
