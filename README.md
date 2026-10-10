# sūveryn-core (AGPL-3.0-or-later)

Engine, chat, RAG, MCP host, API gateway — plus bundled official connectors
and playbooks, and the [models manifest](models/manifest.json) (metadata only; weights are never
committed here).

Stack: Python 3.12, FastAPI, managed as a [uv](https://docs.astral.sh/uv/) workspace; React and TypeScript for the chat UI. Models are served by [llama.cpp](https://github.com/ggml-org/llama.cpp) (`llama-server`).

Related repositories: [suveryn-docs](https://github.com/suveryn/suveryn-docs) (installation, administration, the [hardware benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md)), [suveryn-appliance](https://github.com/suveryn/suveryn-appliance) (OS image and runtime services: PostgreSQL, Keycloak, the model server), [suveryn-brand](https://github.com/suveryn/suveryn-brand) (mark, fonts, tokens), [suveryn-connector-sdk](https://github.com/suveryn/suveryn-connector-sdk) and [suveryn-connectors-registry](https://github.com/suveryn/suveryn-connectors-registry) (connectors).

## Packages

For reviewers: [docs/architecture.md](docs/architecture.md) describes the data flow, where confidential data lives, the invariants the code must keep, design decisions with their evidence, known limitations and a review checklist.


| Package | Status |
|---|---|
| [`packages/engine`](packages/engine/README.md) | Model backend client (llama-server); request, answer, citation and calculation schema |
| [`packages/chat`](packages/chat/README.md) | Grounded answers with numbered citations (`[n]` → `citations[n-1]`) and server-side calculations |
| [`packages/api-gateway`](packages/api-gateway/README.md) | FastAPI app: `POST /v1/chat`, `/v1/documents`, `GET /health` |
| [`packages/rag`](packages/rag/README.md) | Document ingestion (`ocr_fast` extraction, chunking, bge-m3 embeddings, PostgreSQL + pgvector) and retrieval with page-level citations |
| [`packages/chat-ui`](packages/chat-ui/README.md) | The chat interface (React, TypeScript, Vite) |
| `packages/mcp-host`, `connectors`, `playbooks` | Placeholders for later phases |

## Run locally

1. Start llama-server on the GPU machine in **router mode**, so people can choose the model per conversation. [models/llama-server-presets.example.ini](models/llama-server-presets.example.ini) holds the configuration validated in the [October 2026 benchmark](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-10-hardware-benchmark.md) for Qwen3.8-27B (the default) and Mistral Small 3.2 24B; adjust the model paths. The model files are listed, with their sources and checksums, in [models/manifest.json](models/manifest.json).
   ```bash
   llama-server --models-preset models/llama-server-presets.example.ini --models-max 1 --host 127.0.0.1 --port 8080
   ```
   `--models-max 1`: a 24 GB card holds one of these models at a time. A single-model llama-server (`llama-server -m <file> …`) still works; the chat then shows just that model.
2. If llama-server runs on a remote GPU box, forward its port to your machine:
   ```bash
   ssh -N -L 8080:127.0.0.1:8080 root@<gpu-host> -p <ssh-port>
   ```
3. Install and start the gateway. `uv sync` installs only what the gateway needs; on the GPU machine, `uv sync --all-packages` adds `rag` with Docling and PyTorch:
   ```bash
   uv sync
   uv run suveryn-gateway
   ```
   It listens on `http://127.0.0.1:8000`. Settings come from environment variables: `SUVERYN_LLM_BASE_URL` (default `http://127.0.0.1:8080`), `SUVERYN_HOST`, `SUVERYN_PORT`, `SUVERYN_LLM_TIMEOUT_S`.

   The interactive API pages (`/docs`, `/redoc`) are off by default, because FastAPI loads them from public CDNs, which doesn't work air-gapped and contacts third parties. Set `SUVERYN_API_DOCS=1` to turn on `/docs` on a connected development machine. The schema at `/openapi.json` is always available and is served locally.
4. Run the tests (no GPU needed; they use a fake backend):
   ```bash
   uv run pytest
   ```
5. For sign-in, run a development Keycloak as described in [packages/api-gateway/keycloak](packages/api-gateway/keycloak/README.md), or set `SUVERYN_AUTH=off` to work without it on your own machine.
6. Run the chat UI (see [packages/chat-ui](packages/chat-ui/README.md)):
   ```bash
   cd packages/chat-ui && npm ci && npm run dev
   ```

## API

`GET /health` returns 200 when the model backend is ready, and 503 when it is loading or unreachable:

```json
{"status": "ok", "backend": {"reachable": true, "status": "ok", "url": "http://127.0.0.1:8080", "model": "Qwen3.8-27B-UD-Q4_K_M.gguf", "detail": null}, "documents": {"status": "ready", "detail": null}}
```

`documents.status` is `ready`, `starting`, `failed` or `unavailable` (no database or `rag` not installed); it doesn't affect the status code.

Every `/v1/...` request needs a signed-in user: the session cookie from `/auth/login`, or `Authorization: Bearer <Keycloak access token>`. Without one the answer is 401.

`GET /v1/models` lists the installed models: `[{"id": "qwen3.8-27b", "loaded": true, "default": true}, …]`.

`POST /v1/chat` takes `{"messages": [{"role": "user", "content": "..."}], "document_ids": ["<uuid>"], "model": "<id>", "stream": false, "max_tokens": 1024, "temperature": 0}`. `model` is optional (default: the appliance's default model). The last message must be the user's question. `document_ids` is optional: without it the answer is not grounded in any document.

Without streaming it returns:

```json
{"id": "...", "model": "Qwen3.8-27B-UD-Q4_K_M.gguf", "answer": "... [1] ...", "citations": [{"text": "...", "source": {"document_id": "...", "page": 3, "location": "p. 3 · Artikel 2"}}], "calculations": [], "finish_reason": "stop", "usage": {"prompt_tokens": 48, "completion_tokens": 62}}
```

With `"stream": true` it returns Server-Sent Events: `delta` events (`{"text": "..."}`) as the answer is generated, then one `done` event with the same object as above, or an `error` event (`{"message": "..."}`).

**Citations.** With `document_ids`, `citations` holds the passages the model was given, in order, and the marker `[n]` in `answer` refers to `citations[n-1]`; clients show only the cited ones. Without `document_ids`, `citations` is `[]`: the answer is unsourced and must be shown as unverified. A citation with `source: null` is unsourced too.

**Calculations.** Totals and other arithmetic in a grounded answer are computed by the server, not the model; `calculations` lists each one (`expression`, `result`, `figures_not_in_sources`, `error`). See [packages/chat](packages/chat/README.md#calculations).

Documents: `POST /v1/documents` (multipart PDF upload, returns a job), `GET /v1/documents/jobs/{id}`, `GET /v1/documents`, `DELETE /v1/documents/{id}`. See [packages/api-gateway](packages/api-gateway/README.md).

## Licence

`suveryn-core` is licensed under the GNU Affero General Public License, version 3 or (at your option) any later version: SPDX `AGPL-3.0-or-later`. The full text is in [LICENSE](LICENSE).

Not covered by it:

- the Sūveryn name and mark ([trademark policy](https://github.com/suveryn/suveryn-brand/blob/main/TRADEMARK_POLICY.md)); the copies in `packages/chat-ui` are explained in [its brand README](packages/chat-ui/src/brand/README.md);
- third-party software and models, each under its own licence ([UI notices](packages/chat-ui/public/THIRD-PARTY-NOTICES.txt), [models](models/manifest.json)). On a GPU machine, PyTorch installs NVIDIA's CUDA libraries, which are proprietary and redistributed under NVIDIA's licence; see [docs/architecture.md](docs/architecture.md#5-decisions-and-their-evidence).
