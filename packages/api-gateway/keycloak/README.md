# Keycloak for development

The gateway signs people in with Keycloak over OpenID Connect (see [`auth.py`](../src/suveryn_api_gateway/auth.py)). Keycloak is a separate service, like PostgreSQL. On an appliance, [suveryn-appliance](https://github.com/suveryn/suveryn-appliance) installs and configures it. This folder is only for running a **local development** Keycloak that the gateway can talk to:

| File | What |
|---|---|
| [`suveryn-realm.json`](suveryn-realm.json) | The `suveryn` realm: settings, the `suveryn-chat` client and the `suveryn-directory` client with its service account. No human accounts, no secrets, no identity providers |
| [`live_login_check.py`](live_login_check.py) | Signs in through a running Keycloak and gateway the way a browser does, and checks the API gate (optionally with TOTP) |

## What the realm allows

| Identity method | In the dev realm | How an admin changes it |
|---|---|---|
| **Local accounts** (Keycloak's own users, username + password) | On. The baseline every installation has. No self-registration: an administrator adds accounts in the chat, under Administration › Users, with a temporary password. Keycloak's console is needed only for the realm's own settings. Password policy: 12+ characters, not the username or email. Brute-force protection on (5 failures, then increasing waits) | — |
| **LDAP / Active Directory federation** | Not configured, so a plain local-accounts setup works on its own | *User federation → Add LDAP provider*: connection URL, users DN, bind DN and credential, *Edit mode: READ_ONLY*. Directory users then sign in with their directory password; local accounts keep working |
| **TOTP** (FreeOTP, Google Authenticator, …; works offline) | Off by default; required for everyone when an administrator turns it on in Administration › Settings (Filip, 29 October 2026). Then the gateway gives every account without an authenticator app the required action `CONFIGURE_TOTP`, and each new account added in Users gets it with `UPDATE_PASSWORD`; turned off again, `CONFIGURE_TOTP` is taken away and set-up apps stay. Resetting an account's two-step sign-in removes its authenticator app, and adds `CONFIGURE_TOTP` again only while the office requires it. Anyone may set an app up from their account at any time. In the realm itself "Configure OTP" is enabled but not a default action, so an account made another way (`kcadm.sh`, the console) is asked for a code only once it has set one up | For everyone, including accounts made in the console: *Authentication → Required actions → Configure OTP → Set as default action* |
| **Social or online identity providers** (Google, Microsoft personal accounts, itsme, …) | **None, by design.** Not supported at any tier or network mode: they need a live third party and undercut the on-premise promise | Don't add any under *Identity providers*. The realm file has an empty `identityProviders` list, and a test (`test_auth.py`) keeps it that way |
| Belgian eID | Not yet | Planned once offline certificate-revocation checking is designed |

The `suveryn-directory` client (suveryn-tracker#10) is the gateway's read-only view of the office's accounts, so a case's manager can add colleagues by name: a confidential client with a **service account** whose only roles are `view-users` and `view-realm` on this realm (`realm-management`; the second lists the holders of the `suveryn-admin` role, for the badge on their avatar: docs/design/avatars.md), both read-only, no sign-in flow of its own, no redirect URIs. The gateway reads it with `SUVERYN_DIRECTORY_CLIENT_SECRET` (client-credentials grant, then `GET /admin/realms/suveryn/users`); a development Keycloak shows the secret under *Clients → suveryn-directory → Credentials*. Its service-account user is the only account in the realm file. The client has `fullScopeAllowed` off, so the realm maps both roles to its scope (`clientScopeMappings`): without that its token carries no roles and Keycloak refuses the user list (HTTP 403), which a fresh install showed in the Pod check of 5e9a539.

The `suveryn-admin` realm role is what makes someone an administrator. It is a **composite** of `manage-users`, `view-users`, `view-realm` and `view-events` on this realm (`realm-management`), and nothing on the realm's settings or clients, so an administrator's own access token lets the gateway manage the office's accounts for Administration › Users (docs/design/admin.md) without Keycloak's console, with no client or secret of its own. The `suveryn-chat` client's scope carries these roles because the role is mapped to it. Keycloak's admin events name the administrator who made each change, and while no administrator is signed in nothing can be changed. Checked against Keycloak 26.8 with this realm on 28 October 2026: the roles in the chat client's token, listing, adding with a temporary password and the required actions, the role, two-step reset, signing out, switching off, and the sign-in and admin events.

The realm records **sign-in events** and **admin events**, as the appliance's production realm does (suveryn-appliance `keycloak/realm/build_realm.py`): `eventsEnabled` and `adminEventsEnabled` on, both kept 180 days (`eventsExpiration`, and the `adminEventsExpiration` attribute), and `adminEventsDetailsEnabled` off, so an admin event says who changed which account, not the changed record. Administration › Users reads them for each account's last sign-in and for *Sign-ins and changes*, so both work in development too. A test (`test_auth.py`) keeps them on. A realm imported before this keeps its events off: turn them on under *Realm settings → Events*.

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

## Administrators

The realm has one role, **`suveryn-admin`** (no one has it by default). It opens the whole of Administration in the chat (docs/design/admin.md): Users, Cases, Playbooks, Usage and Settings for the office, Status and Backups for the appliance. Because the `suveryn-chat` client has `fullScopeAllowed: false`, the realm maps the role to the client (`scopeMappings`), so it reaches the access token. To make someone an administrator: *Users → user → Role mapping → Assign role → suveryn-admin*, or

```bash
keycloak/bin/kcadm.sh add-roles -r suveryn --uusername <username> --rolename suveryn-admin
```

On a realm imported before this role existed, create it and map it once:

```bash
keycloak/bin/kcadm.sh create roles -r suveryn -s name=suveryn-admin
RID=$(keycloak/bin/kcadm.sh get roles/suveryn-admin -r suveryn --fields id --format csv --noquotes)
keycloak/bin/kcadm.sh create clients/$CID/scope-mappings/realm -r suveryn -b "[{\"id\":\"$RID\",\"name\":\"suveryn-admin\"}]"
```

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
