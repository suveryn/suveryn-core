"""The end-to-end stack: PostgreSQL, Keycloak, the stand-in model server, the gateway and the built chat UI,
on one machine, the way the appliance wires them (e2e/README.md).

    uv run python e2e/stack.py up        # start everything, seed two accounts, wait until the gateway is ready
    uv run python e2e/stack.py down      # stop everything this script started
    uv run python e2e/stack.py stop postgres | keycloak | stub | gateway      # the lifecycle scenarios
    uv run python e2e/stack.py start postgres | keycloak | stub | gateway
    uv run python e2e/stack.py status

PostgreSQL and Keycloak run either as Docker containers (``E2E_SERVICES=docker``: a CI runner) or as the
machine's own PostgreSQL cluster and an unpacked Keycloak (``E2E_SERVICES=local``, with ``E2E_KEYCLOAK_HOME``).
The stub, the gateway and the UI are processes of this user either way. Ports: PostgreSQL 5432, Keycloak 8180,
the stub 8080, the gateway 8000, the UI 5173 (the development realm's redirect URI, keycloak/README.md).

Logs and pid files go to ``e2e/.run/``. Nothing here is confidential: fixed test secrets (realm.py), a fictional
deed, two test accounts.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from realm import CHAT_SECRET, DIRECTORY_SECRET, PUBLIC_URL, prepared_realm  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RUN = HERE / ".run"
MODE = os.environ.get("E2E_SERVICES", "docker")
LIGHT = os.environ.get("E2E_LIGHT", "") == "1"  # no Hugging Face: the light reader and embedder (e2e/light/)
PG_URL = "postgresql://postgres:postgres@localhost:5432"
DB = "suveryn_e2e"
KC_URL = "http://localhost:8180"
ISSUER = f"{KC_URL}/realms/suveryn"
KC_ADMIN = ("admin", "e2e-admin-password")
KC_IMAGE = "quay.io/keycloak/keycloak:26.8.0"
PG_IMAGE = "pgvector/pgvector:pg16"
GATEWAY = "http://127.0.0.1:8000"
STUB = "http://127.0.0.1:8080"

# The two accounts the scenarios use. Passwords meet the realm's policy (12+ characters).
ACCOUNTS = [
    {"username": "notaris.test", "email": "notaris@example.test", "firstName": "Nora", "lastName": "Notaris",
     "password": "Notaris-e2e-2026!", "admin": True},
    {"username": "collega.test", "email": "collega@example.test", "firstName": "Koen", "lastName": "Collega",
     "password": "Collega-e2e-2026!", "admin": False},
]


def sh(*cmd: str, check: bool = True, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, text=True, capture_output=True, **kw)


def wait_for(what: str, probe, timeout: float = 120.0, every: float = 1.0) -> None:
    start = time.monotonic()
    last = None
    while time.monotonic() - start < timeout:
        try:
            if probe():
                print(f"  {what}: ready ({time.monotonic() - start:.0f}s)")
                return
        except Exception as e:  # noqa: BLE001 - a probe's failure is "not yet"
            last = f"{type(e).__name__}: {e}"
        time.sleep(every)
    raise SystemExit(f"{what}: not ready after {timeout:.0f}s ({last})")


def http_ok(url: str, expect: int = 200) -> bool:
    return httpx.get(url, timeout=3.0).status_code == expect


# ----------------------------------------------------------------------------------------------- PostgreSQL

def pg_ready() -> bool:
    return sh("pg_isready", "-h", "localhost", "-p", "5432", "-U", "postgres", check=False).returncode == 0


def psql(sql: str, db: str = "postgres") -> str:
    return sh("psql", f"{PG_URL}/{db}", "-v", "ON_ERROR_STOP=1", "-tAc", sql).stdout.strip()


def postgres_start() -> None:
    if MODE == "docker":
        if sh("docker", "ps", "-aq", "-f", "name=^e2e-postgres$").stdout.strip():
            sh("docker", "start", "e2e-postgres")
        else:
            sh("docker", "run", "-d", "--name", "e2e-postgres", "-p", "5432:5432", "-e", "POSTGRES_PASSWORD=postgres",
               PG_IMAGE, "-c", "wal_recycle=off")
    else:
        sh("pg_ctlcluster", "16", "main", "start", check=False)
    wait_for("postgres", pg_ready, 60)


def postgres_stop() -> None:
    if MODE == "docker":
        sh("docker", "stop", "e2e-postgres")
    else:
        sh("pg_ctlcluster", "16", "main", "stop", "-m", "fast")


def postgres_prepare() -> None:
    for db in (DB, "keycloak"):
        if psql(f"select 1 from pg_database where datname='{db}'") != "1":
            psql(f"create database {db}")
    psql("create extension if not exists vector", DB)


# ------------------------------------------------------------------------------------------------- Keycloak

def keycloak_args() -> list[str]:
    return ["start-dev", "--http-host=0.0.0.0" if MODE == "docker" else "--http-host=127.0.0.1", "--http-port=8180",
            f"--hostname={KC_URL}", "--import-realm", "--db=postgres", "--db-url=jdbc:postgresql://localhost:5432/keycloak",
            "--db-username=postgres", "--db-password=postgres", "--cache=local"]


def keycloak_start() -> None:
    import_dir = RUN / "keycloak-import"
    import_dir.mkdir(parents=True, exist_ok=True)
    (import_dir / "suveryn-realm.json").write_text(json.dumps(prepared_realm(), indent=2), encoding="utf-8")
    env = {"KC_BOOTSTRAP_ADMIN_USERNAME": KC_ADMIN[0], "KC_BOOTSTRAP_ADMIN_PASSWORD": KC_ADMIN[1],
           # As the appliance's Keycloak (suveryn-appliance keycloak/quarkus.properties): a pooled connection is
           # checked before use, so the first request after PostgreSQL restarts doesn't fail on a dead one.
           "QUARKUS_DATASOURCE_JDBC_VALIDATE_ON_BORROW": "true"}
    if MODE == "docker":
        if sh("docker", "ps", "-aq", "-f", "name=^e2e-keycloak$").stdout.strip():
            sh("docker", "start", "e2e-keycloak")
        else:
            sh("docker", "run", "-d", "--name", "e2e-keycloak", "--network", "host",
               *[a for k, v in env.items() for a in ("-e", f"{k}={v}")],
               "-v", f"{import_dir}:/opt/keycloak/data/import:ro", KC_IMAGE, *keycloak_args())
    else:
        home = Path(os.environ.get("E2E_KEYCLOAK_HOME", "")).expanduser()
        if not (home / "bin" / "kc.sh").exists():
            raise SystemExit("E2E_KEYCLOAK_HOME must point at an unpacked Keycloak 26.8 (keycloak/README.md)")
        target = home / "data" / "import"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(import_dir / "suveryn-realm.json", target / "suveryn-realm.json")
        spawn("keycloak", [str(home / "bin" / "kc.sh"), *keycloak_args()], env)
    wait_for("keycloak", lambda: http_ok(f"{ISSUER}/.well-known/openid-configuration"), 180, 2)


def keycloak_stop() -> None:
    if MODE == "docker":
        sh("docker", "stop", "e2e-keycloak")
    else:
        kill("keycloak")


def kc_token() -> str:
    """A master-realm token for the bootstrap administrator. Tried a few times: right after PostgreSQL restarted,
    Keycloak's first request fails on its dead pooled connections (a finding of the lifecycle scenarios)."""
    for attempt in range(4):
        r = httpx.post(f"{KC_URL}/realms/master/protocol/openid-connect/token", timeout=10.0,
                       data={"grant_type": "password", "client_id": "admin-cli", "username": KC_ADMIN[0], "password": KC_ADMIN[1]})
        if r.status_code == 200:
            return r.json()["access_token"]
        time.sleep(1 + attempt)
    r.raise_for_status()
    raise RuntimeError("unreachable")


def seed_accounts() -> None:
    """The two test accounts, with their passwords set and no required actions, so a scenario signs in at once."""
    h = {"Authorization": f"Bearer {kc_token()}"}
    base = f"{KC_URL}/admin/realms/suveryn"
    role = httpx.get(f"{base}/roles/suveryn-admin", headers=h, timeout=10.0).json()
    for a in ACCOUNTS:
        existing = httpx.get(f"{base}/users", headers=h, params={"username": a["username"], "exact": "true"}, timeout=10.0).json()
        if existing:
            uid = existing[0]["id"]
            if not existing[0].get("enabled", True):  # a scenario switched it off and didn't get to switch it back on
                httpx.put(f"{base}/users/{uid}", headers=h, json={**existing[0], "enabled": True}, timeout=10.0).raise_for_status()
        else:
            body = {"username": a["username"], "email": a["email"], "emailVerified": True, "enabled": True,
                    "firstName": a["firstName"], "lastName": a["lastName"], "requiredActions": [],
                    "credentials": [{"type": "password", "value": a["password"], "temporary": False}]}
            r = httpx.post(f"{base}/users", headers=h, json=body, timeout=10.0)
            r.raise_for_status()
            uid = r.headers["Location"].rsplit("/", 1)[1]
        if a["admin"]:
            httpx.post(f"{base}/users/{uid}/role-mappings/realm", headers=h, json=[role], timeout=10.0).raise_for_status()
    print("  accounts: seeded")


# --------------------------------------------------------------------------------------------- processes

def spawn(name: str, cmd: list[str], env: dict[str, str] | None = None, cwd: Path | None = None) -> None:
    RUN.mkdir(exist_ok=True)
    log = open(RUN / f"{name}.log", "ab")
    p = subprocess.Popen(cmd, cwd=cwd or ROOT, env={**os.environ, **(env or {})}, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
    (RUN / f"{name}.pid").write_text(str(p.pid))


def kill(name: str) -> None:
    pidfile = RUN / f"{name}.pid"
    if not pidfile.exists():
        return
    pid = int(pidfile.read_text())
    try:
        os.killpg(pid, signal.SIGTERM)
        for _ in range(50):
            os.killpg(pid, 0)
            time.sleep(0.2)
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    pidfile.unlink(missing_ok=True)


def gateway_env() -> dict[str, str]:
    work = RUN / "work"
    work.mkdir(parents=True, exist_ok=True)
    os.chmod(work, 0o700)
    env = {
        "SUVERYN_HOST": "127.0.0.1", "SUVERYN_PORT": "8000", "SUVERYN_PUBLIC_URL": PUBLIC_URL,
        "SUVERYN_DATABASE_URL": f"{PG_URL}/{DB}",
        "SUVERYN_LLM_BASE_URL": STUB, "SUVERYN_LLM_TIMEOUT_S": "60",
        "SUVERYN_OIDC_ISSUER": ISSUER, "SUVERYN_OIDC_CLIENT_ID": "suveryn-chat", "SUVERYN_OIDC_CLIENT_SECRET": CHAT_SECRET,
        "SUVERYN_DIRECTORY_CLIENT_SECRET": DIRECTORY_SECRET,
        "SUVERYN_WORK_DIR": str(work), "SUVERYN_EXTRACT_UNSANDBOXED": "1",
        "SUVERYN_RAG_DEVICE": "cpu", "SUVERYN_OCR_JOBS": "2",
        "SUVERYN_VERSION": "e2e", "SUVERYN_LOG_LEVEL": "INFO",
        # every scenario signs in afresh from one address; the appliance's 30 a minute would refuse the tenth test
        "SUVERYN_RATE_SIGN_IN": "600",
        # the appliance's backup service isn't here: the gateway reads these files and finds none
        "SUVERYN_BACKUP_STATUS": str(RUN / "backup" / "status.json"),
        "SUVERYN_BACKUP_SETTINGS": str(RUN / "backup" / "backups.json"),
        "SUVERYN_BACKUP_REQUESTS": str(RUN / "backup" / "requests"),
        "SUVERYN_BACKUP_KEY_TEST": str(RUN / "backup" / "key-test"),
    }
    if LIGHT:
        embedder = RUN / "light-embedder"
        if not (embedder / "modules.json").exists():
            print("  light embedder: building")
            sh("uv", "run", "python", str(HERE / "light" / "make_embedder.py"), str(embedder), env={**os.environ, "HF_HUB_OFFLINE": "1"})
        env.update({"SUVERYN_EXTRACT_WRAPPER": str(HERE / "light" / "reader-wrapper.sh"),
                    "SUVERYN_EMBEDDING_MODEL": str(embedder), "HF_HUB_OFFLINE": "1"})
    return env


def gateway_health() -> dict:
    return httpx.get(f"{GATEWAY}/health", timeout=5.0).json()


def gateway_ready() -> bool:
    h = gateway_health()
    parts = {k: v.get("status") for k, v in h.items() if isinstance(v, dict) and "status" in v}
    ok = h.get("status") == "ok" and parts.get("auth") == "ready" and parts.get("documents") == "ready"
    if not ok:
        print(f"    health: {h.get('status')} {parts}")
    return ok


def gateway_start() -> None:
    spawn("gateway", ["uv", "run", "suveryn-gateway"], gateway_env())
    # the reader loads Docling and the embedder loads bge-m3 at start; on a CI runner without a model cache, minutes
    wait_for("gateway", gateway_ready, 900, 5)


def stub_start() -> None:
    spawn("stub", ["uv", "run", "python", str(HERE / "llama_stub.py")])
    wait_for("stub", lambda: http_ok(f"{STUB}/health"), 60)


def ui_start() -> None:
    ui = ROOT / "packages" / "chat-ui"
    if not (ui / "dist" / "index.html").exists():
        print("  ui: building")
        sh("npm", "run", "build", cwd=ui)
    spawn("ui", ["npx", "vite", "preview", "--port", "5173", "--strictPort", "--host", "127.0.0.1"], cwd=ui)
    wait_for("ui", lambda: http_ok(f"{PUBLIC_URL}/") and http_ok(f"{PUBLIC_URL}/health"), 60)


SERVICES = {
    "postgres": (postgres_start, postgres_stop),
    "keycloak": (keycloak_start, keycloak_stop),
    "stub": (stub_start, lambda: kill("stub")),
    "gateway": (gateway_start, lambda: kill("gateway")),
    "ui": (ui_start, lambda: kill("ui")),
}


def up() -> None:
    RUN.mkdir(exist_ok=True)
    postgres_start()
    postgres_prepare()
    keycloak_start()
    seed_accounts()
    stub_start()
    gateway_start()
    ui_start()
    print("up: " + PUBLIC_URL)


def down() -> None:
    for name in ("ui", "gateway", "stub"):
        kill(name)
    if MODE == "docker":
        for c in ("e2e-keycloak", "e2e-postgres"):
            sh("docker", "rm", "-f", c, check=False)
    else:
        kill("keycloak")
        sh("pg_ctlcluster", "16", "main", "stop", "-m", "fast", check=False)
    print("down")


def status() -> None:
    for name, url in (("stub", f"{STUB}/health"), ("gateway", f"{GATEWAY}/health"), ("ui", f"{PUBLIC_URL}/"),
                      ("keycloak", f"{ISSUER}/.well-known/openid-configuration")):
        try:
            print(f"{name}: HTTP {httpx.get(url, timeout=3.0).status_code}")
        except httpx.HTTPError as e:
            print(f"{name}: {type(e).__name__}")
    print(f"postgres: {'ready' if pg_ready() else 'down'}")


def main(argv: list[str]) -> None:
    if len(argv) < 2 or argv[1] not in ("up", "down", "status", "stop", "start"):
        raise SystemExit(__doc__)
    if argv[1] in ("stop", "start"):
        if len(argv) != 3 or argv[2] not in SERVICES:
            raise SystemExit(f"{argv[1]} needs one of: {' '.join(SERVICES)}")
        start, stop = SERVICES[argv[2]]
        (start if argv[1] == "start" else stop)()
        return
    {"up": up, "down": down, "status": status}[argv[1]]()


if __name__ == "__main__":
    main(sys.argv)
