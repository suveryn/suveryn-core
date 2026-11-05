"""The development realm with fixed client secrets, for the end-to-end stack (e2e/README.md).

Keycloak gives a confidential client a random secret at import unless the file carries one. The
development realm carries none (keycloak/README.md: secrets stay out of the repository), so this writes
a copy of it with known secrets into Keycloak's import folder. The secrets are test values for a
stack that lives minutes on a CI runner or a development machine; they are not secrets.

    python e2e/realm.py <import-folder>
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REALM = HERE.parent / "packages" / "api-gateway" / "keycloak" / "suveryn-realm.json"

CHAT_SECRET = "e2e-chat-secret-0123456789abcdef0123456789abcdef"
DIRECTORY_SECRET = "e2e-directory-secret-0123456789abcdef0123456789"
PUBLIC_URL = "http://localhost:5173"


def prepared_realm() -> dict:
    """The development realm as a dict, with the two clients' secrets set."""
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    secrets = {"suveryn-chat": CHAT_SECRET, "suveryn-directory": DIRECTORY_SECRET}
    seen = set()
    for client in realm["clients"]:
        if client["clientId"] in secrets:
            client["secret"] = secrets[client["clientId"]]
            seen.add(client["clientId"])
            if client["clientId"] == "suveryn-chat":
                assert client["redirectUris"] == [f"{PUBLIC_URL}/auth/callback"], client["redirectUris"]
                # The playbook runs' scenario talks to the gateway's API with a bearer token, without a browser (a GPU
                # pod has no Node for the chat UI): the test accounts' password grant, in this test realm only.
                client["directAccessGrantsEnabled"] = True
    missing = set(secrets) - seen
    if missing:
        raise SystemExit(f"realm file lacks clients: {sorted(missing)}")
    return realm


def main(argv: list[str]) -> None:
    if len(argv) != 2:
        raise SystemExit(__doc__)
    folder = Path(argv[1])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "suveryn-realm.json").write_text(json.dumps(prepared_realm(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv)
