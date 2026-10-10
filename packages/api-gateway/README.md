# api-gateway

The HTTP surface (FastAPI). It contains no business logic: it validates requests and calls `chat`, `engine` and, for documents, `rag`.

Document endpoints work when `suveryn-rag` is installed (`uv sync --all-packages`, GPU machine) and `SUVERYN_DATABASE_URL` is set. Otherwise they answer 503, and `/health` reports `documents.status: unavailable`. Saved conversations need only `SUVERYN_DATABASE_URL` (they don't need `suveryn-rag`); without it they answer 503 and `/health` reports `history.status: unavailable`.

| Endpoint | Behaviour |
|---|---|
| `GET /health` | 200 when llama-server is ready (reports the served model); 503 when it is loading, failing or unreachable. Also reports `documents`, `auth` and `history` status. Public |
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
| `GET /v1/conversations` | The caller's saved conversations, most recently changed first: `id`, `title`, `created_at`, `updated_at` (no content) |
| `GET /v1/conversations/{id}` | One saved conversation with its `turns` (404 if unknown, expired or another user's) |
| `PUT /v1/conversations/{id}` | Save a whole conversation (`{title, turns}`) under an id the client chose (a UUID), replacing an earlier save (204). 413 above 2 MB; 404 if the id is another user's |
| `DELETE /v1/conversations/{id}` | Delete one saved conversation (204; 404 if unknown) |
| `DELETE /v1/conversations` | Delete all of the caller's saved conversations (`{"deleted": n}`); the UI's *Delete history* when signing out |
| `GET /v1/usage?start=&end=` | The caller's own token usage (ISO 8601 times with a time zone; default the last 24 hours, `end` defaults to the server's now): `totals`, a zero-filled `series` (5-minute, hourly, daily or weekly buckets starting at local time), `by_kind`. Never a colleague's |
| `GET /v1/admin/usage?start=&end=` | Administrators only (403 otherwise): the same for the whole office, plus `per_user` (username, name, totals, notional cost; most tokens first), the `rates` and the office's notional `cost` |
| `GET`/`PUT /v1/admin/usage/rates` | Administrators only: the notional-cost rates (`input_per_million`, `output_per_million`, `currency`); `PUT` records who changed them |
| `GET /openapi.json` | The API description, served locally |

Saved conversations ([`conversations.py`](src/suveryn_api_gateway/conversations.py), suveryn-tracker#5) are private in the same way, keyed by the Keycloak user id. They are kept until the user deletes them. An administrator can cap their age with `SUVERYN_CONVERSATION_MAX_AGE_DAYS` (whole days; unset means no cap): older conversations, counted from their last change, are deleted when the gateway starts and whenever someone lists theirs. A saved answer quotes the passages it cites, so deleting a document doesn't remove its text from conversations that used it; delete those conversations too.

**Token usage** ([`usage.py`](src/suveryn_api_gateway/usage.py), suveryn-tracker#7). The engine reports every model call's token counts (`suveryn_engine.usage`), and the gateway stores them, one raw row per call, in `token_usage`: user id, time, kind (`chat`, `summary`, `playbook-step`), model and llama-server's own prompt/completion counts. **No text.** As decided in the development context (§5.3), there is one table with raw rows kept indefinitely and no rollups: a few hundred calls a day per office stay quick to sum. Usernames for the administrator's table live in `usage_users`, updated when someone asks a question. Reports group by local time (`SUVERYN_TIMEZONE`, default `Europe/Brussels`). The notional cost uses an administrator-editable rate per million input and output tokens (`usage_rates`), defaulting to $3 and $15 (the published price of a comparable cloud model); hardware and power are not modelled. Usage is informational: nothing is ever limited because of it. Without a database, answers work and the usage endpoints answer 503.

**Administrators** have the Keycloak realm role `suveryn-admin` (see [keycloak/README.md](keycloak/README.md)). The gateway reads realm roles from the access token, where Keycloak puts them, and again at every token refresh, so granting or revoking the role takes effect within one access-token lifetime. `/auth/me` returns `admin: true` for them. With sign-in off (loopback development only) the local user is an administrator.

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
- **Settings:** `SUVERYN_HOST`, `SUVERYN_PORT` (default `127.0.0.1:8000`), `SUVERYN_WORK_DIR`, `SUVERYN_DATABASE_URL`, `SUVERYN_CONVERSATION_MAX_AGE_DAYS`, `SUVERYN_TIMEZONE`, `SUVERYN_API_DOCS`, and the engine's `SUVERYN_LLM_*` (see the [root README](../../README.md#run-locally)).
- **Tests** (`tests/test_api.py`, `test_documents.py`, `test_main.py`, `test_auth.py`) run against a fake llama-server, a fake document service and a fake Keycloak that signs real RS256 tokens and checks PKCE, through `httpx.MockTransport`. No GPU, database or Keycloak is needed. `keycloak/live_login_check.py` checks the same against a real Keycloak.
