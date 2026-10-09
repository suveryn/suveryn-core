# Keycloak for development

The gateway signs people in with Keycloak over OpenID Connect (see [`auth.py`](../src/suveryn_api_gateway/auth.py)). Keycloak is a separate service, like PostgreSQL. On an appliance, [suveryn-appliance](https://github.com/suveryn/suveryn-appliance) installs and configures it. This folder is only for running a **local development** Keycloak that the gateway can talk to:

| File | What |
|---|---|
| [`suveryn-realm.json`](suveryn-realm.json) | The `suveryn` realm: settings and the `suveryn-chat` client. No users, no secrets, no identity providers |
| [`live_login_check.py`](live_login_check.py) | Signs in through a running Keycloak and gateway the way a browser does, and checks the API gate (optionally with TOTP) |

## What the realm allows

| Identity method | In the dev realm | How an admin changes it |
|---|---|---|
| **Local accounts** (Keycloak's own users, username + password) | On. The baseline every installation has. No self-registration: an admin creates users (*Users → Add user*, then *Credentials → Set password*). Password policy: 12+ characters, not the username or email. Brute-force protection on (5 failures, then increasing waits) | — |
| **LDAP / Active Directory federation** | Not configured, so a plain local-accounts setup works on its own | *User federation → Add LDAP provider*: connection URL, users DN, bind DN and credential, *Edit mode: READ_ONLY*. Directory users then sign in with their directory password; local accounts keep working |
| **TOTP** (FreeOTP, Google Authenticator, …; works offline) | Available, not required: "Configure OTP" is enabled but not a default action, and the browser flow asks for a code only from users who have set one up | For one user: *Users → user → Required user actions → Configure OTP*. For everyone: *Authentication → Required actions → Configure OTP → Set as default action* (new users), and add the action to existing users |
| **Social or online identity providers** (Google, Microsoft personal accounts, itsme, …) | **None, by design.** Not supported at any tier or network mode: they need a live third party and undercut the on-premise promise | Don't add any under *Identity providers*. The realm file has an empty `identityProviders` list, and a test (`test_auth.py`) keeps it that way |
| Belgian eID | Not yet | Planned once offline certificate-revocation checking is designed |

The `suveryn-chat` client is confidential (client secret). It allows only the authorization-code flow with **PKCE S256**: no implicit flow, no password grant, no service account, no device flow. Its only redirect URI is the dev UI's callback, `http://localhost:5173/auth/callback`. Tokens: 5-minute access tokens; Keycloak sessions end after 30 minutes idle or 10 hours. Reset-password by email is off (an appliance may have no mail server); an admin resets passwords.

## Run it (on the development machine)

Keycloak 26.8 needs Java 21:

```bash
apt-get install -y openjdk-21-jre-headless
V=26.8.0
curl -fLO https://github.com/keycloak/keycloak/releases/download/$V/keycloak-$V.tar.gz
curl -fLO https://github.com/keycloak/keycloak/releases/download/$V/keycloak-$V.tar.gz.sha1
echo "$(cat keycloak-$V.tar.gz.sha1)  keycloak-$V.tar.gz" | sha1sum -c -
tar --no-same-owner -xzf keycloak-$V.tar.gz && mv keycloak-$V keycloak
mkdir -p keycloak/data/import && cp packages/api-gateway/keycloak/suveryn-realm.json keycloak/data/import/

KC_BOOTSTRAP_ADMIN_USERNAME=admin KC_BOOTSTRAP_ADMIN_PASSWORD='<choose one>' \
  keycloak/bin/kc.sh start-dev --http-host=127.0.0.1 --http-port=8180 \
  --hostname=http://localhost:8180 --import-realm
```

`--hostname` fixes the issuer to `http://localhost:8180/realms/suveryn`, so the browser (through an SSH tunnel) and the gateway (on the same machine) see the same issuer. `start-dev` stores its data in `keycloak/data`; it is for development only. Production Keycloak (TLS, a real database, hardening) is suveryn-appliance's job.

Then read the generated client secret and create a user:

```bash
export KC_CLI_CONFIG=~/.keycloak-kcadm.config
keycloak/bin/kcadm.sh config credentials --server http://localhost:8180 --realm master --user admin
CID=$(keycloak/bin/kcadm.sh get clients -r suveryn -q clientId=suveryn-chat --fields id --format csv --noquotes)
keycloak/bin/kcadm.sh get clients/$CID/client-secret -r suveryn      # → SUVERYN_OIDC_CLIENT_SECRET
keycloak/bin/kcadm.sh create users -r suveryn -s username=notaris.test -s enabled=true -s firstName=Test -s lastName=Notaris
keycloak/bin/kcadm.sh set-password -r suveryn --username notaris.test
```

Keep the secret and passwords in a `0600` file outside the repository.

## Connect the gateway

```bash
export SUVERYN_OIDC_ISSUER=http://localhost:8180/realms/suveryn
export SUVERYN_OIDC_CLIENT_ID=suveryn-chat
export SUVERYN_OIDC_CLIENT_SECRET=...
export SUVERYN_PUBLIC_URL=http://localhost:5173   # where the browser opens the UI
uv run suveryn-gateway
```

`/health` reports `auth.status: ready` once the gateway can read Keycloak's configuration. From a laptop, tunnel both the gateway and Keycloak, and run the UI with `npm run dev` (it proxies `/auth`, `/v1` and `/health` to the gateway):

```bash
ssh -N -L 8000:127.0.0.1:8000 -L 8180:127.0.0.1:8180 root@<gpu-host> -p <ssh-port>
```

Open **http://localhost:5173** (not `127.0.0.1`: the session cookie and the registered redirect URI use `localhost`).

## Check it

```bash
SUVERYN_CHECK_USER=notaris.test SUVERYN_CHECK_PASSWORD=... \
  uv run python packages/api-gateway/keycloak/live_login_check.py
```

For a user with the "Configure OTP" required action, add `--totp-secret-file <path>`: the first run enrols an authenticator, and later runs sign in with password and code.
