# End to end: the stack in a browser

What a VM regression round did by hand, run by a machine on every pull request (`.github/workflows/e2e.yml`): the gateway, the chat UI, Keycloak and PostgreSQL started together as the appliance wires them, a **stand-in model server** in place of llama-server, and Playwright driving Chromium through the scenarios a person walked through. The unit tests cover each package; this covers what happens between them, and what happens when a service goes away and comes back. Why it exists, and what it was built to catch, is in the handbook (`testing/regression-gap-analysis.md`).

| File | What |
|---|---|
| [`stack.py`](stack.py) | `up`, `down`, `status`, and `stop`/`start` of one service: PostgreSQL and Keycloak (Docker containers on CI, the machine's own locally), the stub, the gateway and the built UI (`vite preview` on 5173, the development realm's redirect URI) as processes. Seeds two accounts. Logs and pids in `.run/` |
| [`llama_stub.py`](llama_stub.py) | The stand-in model server: llama-server's router-mode API, answers made from the prompt (a cited sentence of the matching excerpt; a playbook's facts table from keywords), thinking on request, and three hooks a question can trigger: `e2e:think-too-long`, `e2e:slow`, `e2e:error` |
| [`realm.py`](realm.py) | The development realm with fixed client secrets, written into Keycloak's import folder |
| [`tests/test_stub_contract.py`](tests/test_stub_contract.py) | The stub against the real `LlamaServerClient`, in-process: a change on either side fails here first |
| [`tests/test_walkthrough.py`](tests/test_walkthrough.py) | Sign in; a document read and an answer that cites it (the injection attempt flagged, never followed); *Thorough* that thinks without answering, asked again; a case with a colleague and deed intake to its summary; the colleague's view; every Administration page and Status; an account switched off whose session ends within seconds; a new account's first sign-in with its temporary password; sign out |
| [`tests/test_lifecycle.py`](tests/test_lifecycle.py) | PostgreSQL stopped and started: nobody signed out, the stores reconnect, the first upload after works; Keycloak stopped and started: `/health` notices, the session survives, a fresh sign-in works after; the model server away: the answer says so in words, and works again after; the sign-in page with the database down |
| [`light/`](light/) | **Light mode**, for a development machine that can't reach Hugging Face: a reader that takes a PDF's text layer (no OCR, no layout) and a static 1,024-dimension embedder. CI never uses it |

## Run it

CI does this on `ubuntu-latest` with Docker for PostgreSQL and Keycloak, the real reader (Docling, OCR) on the CPU and the real embedder, both cached between runs. Locally:

```bash
uv sync --all-packages --dev --group e2e && uv run playwright install chromium
(cd packages/chat-ui && npm ci && npm run build)

# PostgreSQL and Keycloak as containers (Docker present):
E2E_SERVICES=docker uv run python e2e/stack.py up
# or the machine's own PostgreSQL 16 cluster (with pgvector) and an unpacked Keycloak 26.8 (keycloak/README.md):
E2E_SERVICES=local E2E_KEYCLOAK_HOME=~/keycloak uv run python e2e/stack.py up

uv run pytest e2e/tests -v
uv run python e2e/stack.py down
```

The stack listens on `http://localhost:5173`; sign in as `notaris.test` (an administrator) or `collega.test` (`stack.py`, `ACCOUNTS`) to look at it yourself. `stack.py status` says what is up; `.run/<service>.log` says why something isn't. A failing scenario leaves a full-page screenshot in `.run/shots/`; CI uploads those and the logs as the `e2e-run` artifact.

**Light mode** (`E2E_LIGHT=1`): without Hugging Face the real reader and embedder can't load their models. The light reader and embedder in `light/` stand in; scenarios then run on a born-digital PDF's text only, and retrieval is crude. Good enough to develop a scenario; not what CI runs, so run the suite on CI before trusting a change.

## Writing a scenario

- One scenario is one thing a person does, from sign-in to the result, with waiting assertions (`expect(...)`), never `sleep`. The helpers in `tests/conftest.py` (`sign_in`, `upload`, `ask`, `new_case`, `administration`, `service`) are the vocabulary; add to them rather than repeating steps.
- Find elements by role and accessible name, as a screen reader would: the names are the UI's own strings, so a scenario fails when the UI's words change, which is right. A regular expression as a name can't contain `/`.
- A case reference is unique in the office: make one per run (`E2E/<stamp>`), and leave the stack as you found it (an account switched off is switched back on; `stack_up` re-enables the two accounts at the start of a run).
- Nothing confidential, ever: the fictional trap deed (`packages/rag/tests/trap_deed.py`), the two test accounts, fixed test secrets. Screenshots are uploaded as CI artifacts.
- A finding is a finding: a scenario that shows a defect is kept as it should pass, marked `xfail` with the reason and the tracker issue, and the marker goes with the fix. Two came out of writing the suite: Keycloak's first request after a PostgreSQL restart fails on dead pooled connections, and the member search's suggestions don't open when the directory answers after the last keystroke.

## What it doesn't cover

The image, the installer, the encrypted disk, the TPM, a reboot, a restore onto a fresh machine: those are suveryn-appliance's `run-vm-tests`. A real model on real documents: `packages/rag/tests/test_answers_e2e.py` on the GPU machine, by hand, before a model or prompt change. Copy and design: a person, once per release.
