# api-gateway

The HTTP surface (FastAPI). It contains no business logic: it validates requests and calls the engine.

| Endpoint | Behaviour |
|---|---|
| `GET /health` | 200 when llama-server is ready (reports the served model); 503 when it is loading, failing or unreachable |
| `POST /v1/chat` | `stream: false` returns a `ChatResponse` (JSON); 502 if the backend fails |
| `POST /v1/chat` with `stream: true` | Server-Sent Events: `delta` events (`{text}`), then exactly one `done` (a full `ChatResponse`) or `error` (`{message}`). After `error`, discard the partial text |
| `GET /openapi.json` | The API description, served locally |

Key points for reviewers:

- **No auth yet**, so the gateway binds to `127.0.0.1` (`SUVERYN_HOST` overrides). Keycloak integration (OIDC login, token validation) belongs in this package later; Keycloak itself is installed by `suveryn-appliance`.
- **`/docs` and `/redoc` are off** unless `SUVERYN_API_DOCS=1`, because FastAPI loads them from public CDNs. That breaks air-gapped installs and contacts third parties.
- **Request and answer text are not logged**; the access log has method, path and status only.
- **Tests** (`tests/test_api.py`) run against a fake llama-server through `httpx.MockTransport`, so no GPU is needed.
