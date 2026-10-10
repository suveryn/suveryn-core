# api-gateway

The HTTP surface (FastAPI). It contains no business logic: it validates requests and calls `chat`, `engine` and, for documents, `rag`.

Document endpoints work when `suveryn-rag` is installed (`uv sync --all-packages`, GPU machine) and `SUVERYN_DATABASE_URL` is set. Otherwise they answer 503, and `/health` reports `documents.status: unavailable`.

| Endpoint | Behaviour |
|---|---|
| `GET /health` | 200 when llama-server is ready (reports the served model); 503 when it is loading, failing or unreachable. Also reports `documents` and `auth` status. Public |
| `GET /auth/login` | Starts signing in: redirects to the Keycloak login page (authorization code + PKCE). Public |
| `GET /auth/callback` | Keycloak sends the browser back here; the gateway exchanges the code, validates the tokens and sets the session cookie |
| `GET /auth/me` | The signed-in user (`username`, `name`), or 401 |
| `POST /auth/logout` | Ends the session; returns `logout_url`, Keycloak's end-session URL, which the UI opens to end the Keycloak session too |
| `POST /v1/chat` | `stream: false` returns a `ChatResponse` (JSON); 502 if the backend fails; 422 if the request is invalid (e.g. the last message isn't the user's, or more than 200 messages) |
| `POST /v1/chat` with `stream: true` | Server-Sent Events: `status` events before the first word (`{step, passages, complete, model}`; `step` is `searching`, `loading_model`, `reading` or `writing`, and only real pipeline steps are reported), then `delta` events (`{text}`), then exactly one `done` (a full `ChatResponse`) or `error` (`{message}`). After `error`, discard the partial text. An unexpected server error gives a generic message, never the exception text |
| `POST /v1/chat` with `document_ids` | A grounded answer: `[n]` markers in `answer`, `citations[n-1]` holds the passage with its page. 503 if document search is unavailable |
| `POST /v1/documents` | Upload a PDF (multipart `file`, ≤100 MB). Returns a job at once (202); 415 if not a PDF; 413 if too large (checked from `Content-Length` before the body is read); 411 without `Content-Length` |
| `GET /v1/documents/jobs/{id}` | Job status: `queued`, `processing`, `ready`, `needs_review` or `failed`, plus `document_id` when stored |
| `GET /v1/documents` | Stored documents (newest first) and uploads still in progress or failed (finished jobs are forgotten after an hour). 503 if the database can't be reached after one reconnect |
| `DELETE /v1/documents/{id}` | Delete a document and its passages (204; 404 if unknown) |
| `GET /openapi.json` | The API description, served locally |

Documents are private to the user who uploaded them: every document endpoint, upload job and grounded chat sees only the caller's own, and another user's document gets 404, like a missing one (`owner_of` in `app.py`).

Every `/v1/...` endpoint needs a signed-in user: 401 without one, 503 if sign-in isn't configured or Keycloak can't be reached.

## Sign-in

[`auth.py`](src/suveryn_api_gateway/auth.py) connects the gateway to Keycloak over OpenID Connect. Keycloak itself is a separate service: installed by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance) on an appliance, and run locally for development as described in [keycloak/README.md](keycloak/README.md).

- **Backend-for-frontend.** The gateway is a confidential client and runs the authorization-code flow with PKCE (S256) itself. Tokens stay in the gateway's memory. The browser gets only an opaque session cookie: HttpOnly, SameSite=Lax, and `Secure` with a `__Host-` name when `SUVERYN_PUBLIC_URL` is https. JavaScript in the UI never sees a token.
- **Login safety.** `state` is bound to the browser by a short-lived cookie (no login CSRF) and can be used once; a `nonce` ties the ID token to the login; after login the gateway redirects only to a path on its own site (no open redirect).
- **Token validation.** Signature against Keycloak's published keys (RS256 only; `none` and HMAC are refused), issuer, expiry (30 s leeway), audience for ID tokens, and authorised party for access tokens.
- **Sessions.** Access tokens are refreshed shortly before they expire. If Keycloak refuses the refresh (user disabled, session ended by an admin), the session ends: revocation takes effect within one access-token lifetime (5 minutes in the dev realm). Sessions live in memory, so a gateway restart signs everyone out.
- **Cross-site requests.** `POST`/`PUT`/`PATCH`/`DELETE` with a session cookie must carry the UI's own `Origin`; otherwise 403.
- **API clients** may send `Authorization: Bearer <access token>` instead of a cookie; the same validation applies.
- **Identity methods** are Keycloak's choice: local accounts, optionally LDAP/AD federation and TOTP. **No social or online identity providers**, by design.

| Variable | Meaning |
|---|---|
| `SUVERYN_OIDC_ISSUER` | Keycloak realm URL, e.g. `http://localhost:8180/realms/suveryn` |
| `SUVERYN_OIDC_CLIENT_ID` | Default `suveryn-chat` |
| `SUVERYN_OIDC_CLIENT_SECRET` | The client's secret (keep it in a `0600` file) |
| `SUVERYN_PUBLIC_URL` | The URL people open the UI at; the callback is `<this>/auth/callback`, and it is the only accepted `Origin` |
| `SUVERYN_AUTH=off` | Development only: no sign-in. Refused at start unless the gateway binds to a loopback address |

Key points for reviewers:

- **Binding.** The gateway binds to `127.0.0.1` unless `SUVERYN_HOST` says otherwise. On a network it should sit behind the appliance's TLS reverse proxy, with an https `SUVERYN_PUBLIC_URL`; the gateway warns when it binds to a network address with an http public URL.
- **`/docs` and `/redoc` are off** unless `SUVERYN_API_DOCS=1`, because FastAPI loads them from public CDNs. That breaks air-gapped installs and contacts third parties.
- **Request and answer text are not logged**; the access log has method, path and status only.
- **Uploads never touch `/tmp`.** Starlette writes an upload over 1 MB to a temporary file before our code sees it. The gateway points `tempfile` and `TMPDIR` at `<SUVERYN_WORK_DIR>/tmp/<pid>` (0700, removed on exit; folders of crashed processes are removed on start). `suveryn-gateway` does this before starting; the app does it again on start-up when documents are enabled, so bare `uvicorn suveryn_api_gateway.app:app` is safe too.
- **Settings:** `SUVERYN_HOST`, `SUVERYN_PORT` (default `127.0.0.1:8000`), `SUVERYN_WORK_DIR`, `SUVERYN_DATABASE_URL`, `SUVERYN_API_DOCS`, and the engine's `SUVERYN_LLM_*` (see the [root README](../../README.md#run-locally)).
- **Tests** (`tests/test_api.py`, `test_documents.py`, `test_main.py`, `test_auth.py`) run against a fake llama-server, a fake document service and a fake Keycloak that signs real RS256 tokens and checks PKCE, through `httpx.MockTransport`. No GPU, database or Keycloak is needed. `keycloak/live_login_check.py` checks the same against a real Keycloak.
