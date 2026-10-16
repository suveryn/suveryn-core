# api-gateway

The HTTP surface (FastAPI). It contains no business logic: it validates requests and calls `chat`, `engine` and, for documents, `rag`.

Document endpoints work when `suveryn-rag` is installed (`uv sync --all-packages`, GPU machine) and `SUVERYN_DATABASE_URL` is set. Otherwise they answer 503, and `/health` reports `documents.status: unavailable`. Saved conversations need only `SUVERYN_DATABASE_URL` (they don't need `suveryn-rag`); without it they answer 503 and `/health` reports `history.status: unavailable`.

| Endpoint | Behaviour |
|---|---|
| `GET /health` | 200 when llama-server is ready (reports the served model); 503 when it is loading, failing or unreachable. Also reports `documents`, `auth`, `history` and `usage` status. Public, so states only: no addresses or error texts (the server log has them) |
| `GET /auth/login` | Starts signing in: redirects to the Keycloak login page (authorization code + PKCE). Public |
| `GET /auth/callback` | Keycloak sends the browser back here; the gateway exchanges the code, validates the tokens and sets the session cookie |
| `GET /auth/me` | The signed-in user (`username`, `name`), or 401 |
| `POST /auth/logout` | Ends the session; returns `logout_url`, Keycloak's end-session URL, which the UI opens to end the Keycloak session too |
| `POST /v1/chat` | `stream: false` returns a `ChatResponse` (JSON); 502 if the backend fails; 422 if the request is invalid (e.g. the last message isn't the user's, or more than 200 messages) |
| `POST /v1/chat` with `stream: true` | Server-Sent Events: `status` events before the first word (`{step, passages, complete, model}`; `step` is `searching`, `loading_model`, `reading` or `writing`, and only real pipeline steps are reported), then `delta` events (`{text}`), then exactly one `done` (a full `ChatResponse`) or `error` (`{message}`). After `error`, discard the partial text. An unexpected server error gives a generic message, never the exception text |
| `POST /v1/chat` with `document_ids` | A grounded answer: `[n]` markers in `answer`, `citations[n-1]` holds the passage with its page. 503 if document search is unavailable. With `case_id`, the documents must be uploaded documents of that case (never sūveryn's own output), and the caller must be able to read it; without, the caller's own |
| `POST /v1/documents[?case=]` | Upload a PDF (multipart `file`, ≤100 MB) into the caller's personal space, or into a case (a contributor's right; 404 for a case the caller may not see, 403 for one they may only read or that is closed). Returns a job at once (202); 415 if not a PDF; 413 if too large (checked from `Content-Length` before the body is read); 411 without `Content-Length`; 429 when 20 of the caller's documents (or 200 in all) are waiting. A PDF over `SUVERYN_MAX_PAGES` pages (2,000) fails its job |
| `GET /v1/documents/jobs/{id}` | Job status: `queued`, `processing`, `ready`, `needs_review` or `failed`, plus `document_id` when stored |
| `GET /v1/documents[?case=]` | Stored documents (newest first) in the caller's personal space, or in a case, and the caller's uploads there still in progress or failed (finished jobs are forgotten after an hour). Each has its `origin` (`uploaded`, `generated`, `playbook`) and `uploaded_by`. 503 if the database can't be reached after one reconnect |
| `GET /v1/documents/{id}/conversations` | The caller's saved conversations that cite or attach the document (asked before deleting it) |
| `DELETE /v1/documents/{id}?conversations=clean\|delete[&case=]` | Delete a document and its passages (204; 404 if unknown or outside the personal space or the case named; in a case, the manager's right). Saved conversations citing it lose its passages, headings and file name (`clean`, the default), or are deleted too (`delete`) |
| `GET /v1/conversations[?case=]` | The caller's saved conversations in their personal space, or in a case, most recently changed first: `id`, `title`, `created_at`, `updated_at`, `case_id` (no content) |
| `GET /v1/conversations/{id}` | One saved conversation with its `turns` (404 if unknown, expired or another user's) |
| `PUT /v1/conversations/{id}` | Save a whole conversation (`{title, turns, case_id?}`) under an id the client chose (a UUID), replacing an earlier save (204). A new conversation goes into `case_id` (or the personal space) and stays there. 413 above 2 MB; 404 if the id is another user's or the case can't be seen |
| `GET /v1/cases[?closed=true]` | The cases the caller may see (suveryn-tracker#10): open ones first, most recently active first, each with `my_role` (`reader`, `contributor`, `manager`, or null for an administrator who only sees it exists). Closed cases only with `closed=true` |
| `POST /v1/cases` | Open a case: `{reference, name, type, subject?, access?}` (201). The reference is the office's own file number, unique on the appliance (409 if taken); never a client's name. The caller becomes its manager |
| `GET /v1/cases/{id}` | One case (404 if unknown or not visible to the caller; 403 for an administrator who isn't a member) |
| `PATCH /v1/cases/{id}` | Change reference, name, type, subject or access (`default`, `restricted`): the manager's right (403 otherwise, or when the case is closed) |
| `DELETE /v1/cases/{id}` | Delete a case with its documents and conversations (204): the manager's right. For a case opened by mistake; closing (stage 3 of the design) is the normal end |
| `DELETE /v1/conversations/{id}` | Delete one saved conversation (204; 404 if unknown) |
| `DELETE /v1/conversations` | Delete all of the caller's saved conversations (`{"deleted": n}`); the UI's *Delete history* when signing out |
| `GET /v1/usage?start=&end=` | The caller's own token usage (ISO 8601 times with a time zone; default the last 24 hours, `end` defaults to the server's now): `totals`, a zero-filled `series` (5-minute, hourly, daily or weekly buckets starting at local time), `by_kind`. Never a colleague's |
| `GET /v1/admin/usage?start=&end=` | Administrators only (403 otherwise): the same for the whole office, plus `per_user` (username, name, totals, notional cost; most tokens first), the `rates` and the office's notional `cost` |
| `GET`/`PUT /v1/admin/usage/rates` | Administrators only: the notional-cost rates (`input_per_million`, `output_per_million`, `currency`); `PUT` records who changed them |
| `GET /openapi.json` | The API description, served locally |

Saved conversations ([`conversations.py`](src/suveryn_api_gateway/conversations.py), suveryn-tracker#5) are private in the same way, keyed by the Keycloak user id. They are kept until the user deletes them. An administrator can cap their age with `SUVERYN_CONVERSATION_MAX_AGE_DAYS` (whole days; unset means no cap): older conversations, counted from their last change, are deleted when the gateway starts and whenever someone lists theirs. A saved answer quotes the passages it cites; deleting a document takes them out of every saved conversation, or deletes those conversations (suveryn-tracker#12). The answer text itself stays.

**Cases** ([`cases.py`](src/suveryn_api_gateway/cases.py), suveryn-tracker#10; design in [docs/design/cases.md](../../docs/design/cases.md)). A case is the file a confidential profession works on. Every document and conversation is in one scope: a case (`case_id`), or the uploader's **personal space** (no case; the user's own, as before cases existed; documents stored before cases land there, per owner). A request names its case with `?case=` (documents, conversations) or `case_id` (chat); the gateway decides once per request (`_scope`) whether the caller may `read`, `contribute` or `manage` there with the one authorisation function `may(user, case, role, action, office_wide)`, and the rag store then only looks inside that scope. A case the caller may not see is 404, like a missing one. Only uploaded documents are sources for answers; a document sūveryn generated is listed but never cited. The default access is per appliance: `SUVERYN_CASES_DEFAULT_ACCESS=members` (the default: a case is its members' only) or `office` (everyone signed in reads an unrestricted case; a manager can restrict one). This is stage 1 of the design: a case has one member, its creator and manager. Members and roles, the access log, closing and the keep period, and shared conversations follow. Without a database the case endpoints answer 503 and `/health` reports `cases.status: unavailable`.

**Token usage** ([`usage.py`](src/suveryn_api_gateway/usage.py), suveryn-tracker#7). The engine reports every model call's token counts (`suveryn_engine.usage`), and the gateway stores them, one raw row per call, in `token_usage`: user id, time, kind (`chat`, `summary`, `playbook-step`), model and llama-server's own prompt/completion counts. **No text.** As decided in the development context (§5.3), there is one table with raw rows kept indefinitely and no rollups: a few hundred calls a day per office stay quick to sum. Usernames for the administrator's table live in `usage_users`, updated when someone asks a question. Reports group by local time (`SUVERYN_TIMEZONE`, default `Europe/Brussels`). The notional cost uses an administrator-editable rate per million input and output tokens (`usage_rates`), defaulting to $3 and $15 (the published price of a comparable cloud model); hardware and power are not modelled. Usage is informational: nothing is ever limited because of it. Without a database, answers work and the usage endpoints answer 503.

**Administrators** have the Keycloak realm role `suveryn-admin` (see [keycloak/README.md](keycloak/README.md)). The gateway reads realm roles from the access token, where Keycloak puts them, and again at every token refresh, so granting or revoking the role takes effect within one access-token lifetime. `/auth/me` returns `admin: true` for them. With sign-in off (loopback development only) the local user is an administrator.

Documents are private to the user who uploaded them: every document endpoint, upload job and grounded chat sees only the caller's own, and another user's document gets 404, like a missing one (`owner_of` in `app.py`).

Every `/v1/...` endpoint needs a signed-in user: 401 without one, 503 if sign-in isn't configured or Keycloak can't be reached.

## Sign-in

[`auth.py`](src/suveryn_api_gateway/auth.py) connects the gateway to Keycloak over OpenID Connect. Keycloak itself is a separate service: installed by [suveryn-appliance](https://github.com/suveryn/suveryn-appliance) on an appliance, and run locally for development as described in [keycloak/README.md](keycloak/README.md).

- **Backend-for-frontend.** The gateway is a confidential client and runs the authorization-code flow with PKCE (S256) itself. Tokens stay in the gateway's memory. The browser gets only an opaque session cookie: HttpOnly, SameSite=Lax, and `Secure` with a `__Host-` name when `SUVERYN_PUBLIC_URL` is https. JavaScript in the UI never sees a token.
- **Login safety.** A sign-in in progress (`state`, `nonce`, PKCE verifier, return path) travels in a short-lived HttpOnly cookie, encrypted with AES-GCM under a key derived from the client secret: it is bound to the browser that started it (no login CSRF), can be used once, and the server keeps nothing for sign-ins that are never finished, so a flood of `/auth/login` can't push out a real user's. A `nonce` ties the ID token to the login; after login the gateway redirects only to a path on its own site (no open redirect).
- **Rate limits** ([`ratelimit.py`](src/suveryn_api_gateway/ratelimit.py)): sign-in 30 per minute per client address, questions 20 and uploads 30 per minute per user; over the limit the answer is 429 with `Retry-After`. Set with `SUVERYN_RATE_SIGN_IN`, `SUVERYN_RATE_CHAT` and `SUVERYN_RATE_UPLOADS` (`0` turns one off). Behind a reverse proxy on another machine every request seems to come from the proxy, so raise the sign-in limit there or leave it to the proxy.
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
