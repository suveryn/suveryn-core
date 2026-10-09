# api-gateway

The HTTP surface (FastAPI). It contains no business logic: it validates requests and calls `chat`, `engine` and, for documents, `rag`.

Document endpoints work when `suveryn-rag` is installed (`uv sync --all-packages`, GPU machine) and `SUVERYN_DATABASE_URL` is set. Otherwise they answer 503, and `/health` reports `documents.status: unavailable`.

| Endpoint | Behaviour |
|---|---|
| `GET /health` | 200 when llama-server is ready (reports the served model); 503 when it is loading, failing or unreachable |
| `POST /v1/chat` | `stream: false` returns a `ChatResponse` (JSON); 502 if the backend fails; 422 if the request is invalid (e.g. the last message isn't the user's, or more than 200 messages) |
| `POST /v1/chat` with `stream: true` | Server-Sent Events: `delta` events (`{text}`), then exactly one `done` (a full `ChatResponse`) or `error` (`{message}`). After `error`, discard the partial text. An unexpected server error gives a generic message, never the exception text |
| `POST /v1/chat` with `document_ids` | A grounded answer: `[n]` markers in `answer`, `citations[n-1]` holds the passage with its page. 503 if document search is unavailable |
| `POST /v1/documents` | Upload a PDF (multipart `file`, ≤100 MB). Returns a job at once (202); 415 if not a PDF; 413 if too large (checked from `Content-Length` before the body is read); 411 without `Content-Length` |
| `GET /v1/documents/jobs/{id}` | Job status: `queued`, `processing`, `ready`, `needs_review` or `failed`, plus `document_id` when stored |
| `GET /v1/documents` | Stored documents (newest first) and uploads still in progress or failed (finished jobs are forgotten after an hour). 503 if the database can't be reached after one reconnect |
| `DELETE /v1/documents/{id}` | Delete a document and its passages (204; 404 if unknown) |
| `GET /openapi.json` | The API description, served locally |

Key points for reviewers:

- **No auth yet**, so the gateway binds to `127.0.0.1` (`SUVERYN_HOST` overrides). Keycloak integration (OIDC login, token validation) belongs in this package later; Keycloak itself is installed by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance).
- **`/docs` and `/redoc` are off** unless `SUVERYN_API_DOCS=1`, because FastAPI loads them from public CDNs. That breaks air-gapped installs and contacts third parties.
- **Request and answer text are not logged**; the access log has method, path and status only.
- **Uploads never touch `/tmp`.** Starlette writes an upload over 1 MB to a temporary file before our code sees it. The gateway points `tempfile` and `TMPDIR` at `<SUVERYN_WORK_DIR>/tmp/<pid>` (0700, removed on exit; folders of crashed processes are removed on start). `suveryn-gateway` does this before starting; the app does it again on start-up when documents are enabled, so bare `uvicorn suveryn_api_gateway.app:app` is safe too.
- **Settings:** `SUVERYN_HOST`, `SUVERYN_PORT` (default `127.0.0.1:8000`), `SUVERYN_WORK_DIR`, `SUVERYN_DATABASE_URL`, `SUVERYN_API_DOCS`, and the engine's `SUVERYN_LLM_*` (see the [root README](../../README.md#run-locally)).
- **Tests** (`tests/test_api.py`, `test_documents.py`, `test_main.py`) run against a fake llama-server through `httpx.MockTransport` and a fake document service, so no GPU or database is needed.
