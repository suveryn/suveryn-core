# sūveryn-core (AGPL-3.0)

Engine, chat, RAG, MCP host, API gateway — plus bundled official connectors
and playbooks, and the models manifest (metadata only; weights are never
committed here).

Stack: Python 3.12, FastAPI, managed as a [uv](https://docs.astral.sh/uv/) workspace. Models are served by llama.cpp (`llama-server`).

## Packages

| Package | Status |
|---|---|
| `packages/engine` | Model backend client (llama-server), answer/citation schema |
| `packages/api-gateway` | FastAPI app: `POST /v1/chat`, `GET /health` |
| `packages/rag` | Document ingestion (`ocr_fast` extraction, chunking, bge-m3 embeddings, PostgreSQL + pgvector) and retrieval with page-level citations. See [packages/rag/README.md](packages/rag/README.md) |
| `packages/chat`, `mcp-host`, `connectors`, `playbooks` | Placeholders, built in later slices |

## Run locally

1. Start llama-server on the GPU machine. This is the configuration validated in the October 2026 benchmark. Qwen3.8-27B is the default; Mistral Small 3.2 24B also works (leave out the last line).
   ```bash
   llama-server -m Qwen3.8-27B-UD-Q4_K_M.gguf \
     -ngl 99 -fa on -ctk q8_0 -ctv q8_0 \
     -np 4 -kvu -c 65536 -cram 32768 \
     --jinja --chat-template-kwargs '{"enable_thinking":false}'
   ```
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

## API

`GET /health` returns 200 when the model backend is ready, and 503 when it is loading or unreachable:

```json
{"status": "ok", "backend": {"reachable": true, "status": "ok", "url": "http://127.0.0.1:8080", "model": "Qwen3.8-27B-UD-Q4_K_M.gguf", "detail": null}}
```

`POST /v1/chat` takes `{"messages": [{"role": "user", "content": "..."}], "stream": false, "max_tokens": 1024, "temperature": 0}`.

Without streaming it returns:

```json
{"id": "...", "model": "Qwen3.8-27B-UD-Q4_K_M.gguf", "answer": "...", "citations": [], "finish_reason": "stop", "usage": {"prompt_tokens": 48, "completion_tokens": 62}}
```

With `"stream": true` it returns Server-Sent Events: `delta` events (`{"text": "..."}`) as the answer is generated, then one `done` event with the same object as above, or an `error` event (`{"message": "..."}`).

**Citations.** Every answer has a `citations` list. Each entry is `{"text": "...", "source": null}` until RAG is wired in. Then `source` becomes `{"document_id": "...", "page": 3, "location": "art. 2"}`. Clients must treat `source: null` as unsourced. Until then the list is always empty, and answers are not grounded in any document.
