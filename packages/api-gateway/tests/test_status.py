"""Administration › Status (docs/design/admin.md, artboards 30 and 39): six checks in plain words, counts only."""

from test_usage import ALICE, BOB, as_user, setup  # noqa: F401 - the fixture


def test_the_checks_are_for_administrators_and_say_since_when_one_fails(setup, tmp_path, monkeypatch):  # noqa: F811
    from suveryn_api_gateway.routes import status

    c, kc, _ = setup
    monkeypatch.setattr(status, "DATA_PATH", tmp_path)
    user, admin = as_user(kc, BOB), as_user(kc, ALICE, admin=True)
    assert c.get("/v1/admin/status", headers=user).status_code == 403
    body = c.get("/v1/admin/status", headers=admin).json()
    checks = {x["id"]: x for x in body["checks"]}
    assert list(checks) == ["answering", "reading", "signin", "data", "disk", "clock"]
    assert checks["answering"]["ok"] and checks["answering"]["in_progress"] == 0
    assert checks["signin"]["ok"] and checks["data"]["ok"]
    # this test app reads no documents: reading doesn't work, and says since when
    assert not checks["reading"]["ok"] and checks["reading"]["since"] is not None
    assert checks["disk"]["free"] > 0 and checks["disk"]["total"] >= checks["disk"]["free"]

    # a failure keeps the time it was first seen, check after check
    monkeypatch.setattr(status, "FRESH_S", 0)
    first = checks["reading"]["since"]
    again = {x["id"]: x for x in c.get("/v1/admin/status", headers=admin).json()["checks"]}
    assert again["reading"]["since"] == first


def test_a_nearly_full_disk_is_not_enough(setup, monkeypatch):  # noqa: F811
    from suveryn_api_gateway.routes import status

    c, kc, _ = setup
    monkeypatch.setattr(status, "FRESH_S", 0)
    monkeypatch.setattr(status, "_disk", lambda: (5 * 1024**3, 2 * 1024**4))  # 5 GB of 2 TB
    disk = c.get("/v1/admin/status", headers=as_user(kc, ALICE, admin=True)).json()["checks"][4]
    assert disk["id"] == "disk" and not disk["ok"]


def test_status_shows_the_appliances_version(tmp_path, monkeypatch):
    """Decision, 29 October: Status shows the version, without the installation having to set it."""
    from suveryn_api_gateway.routes import status

    monkeypatch.delenv("SUVERYN_VERSION", raising=False)
    monkeypatch.setattr(status, "OS_RELEASE", tmp_path / "os-release")
    monkeypatch.setattr(status, "CORE_BUILT", tmp_path / "built")
    assert status.appliance_version() is None  # a development machine
    (tmp_path / "built").write_text("suveryn-core@a34d3fb3b732847d619cffb26cd26e463d7ae929\n")
    assert status.appliance_version() == "core a34d3fb"  # installed with the provisioning
    (tmp_path / "os-release").write_text('ID=ubuntu\nIMAGE_ID="suveryn"\nIMAGE_VERSION="1.2.0"\n')
    assert status.appliance_version() == "1.2.0 · core a34d3fb"  # the read-only system
    (tmp_path / "os-release").write_text('ID=ubuntu\nIMAGE_ID="other"\nIMAGE_VERSION="9"\n')
    assert status.appliance_version() == "core a34d3fb"
    monkeypatch.setenv("SUVERYN_VERSION", "1.2.1-rc1")
    assert status.appliance_version() == "1.2.1-rc1"


def test_every_answer_of_status_is_what_the_description_says(setup, tmp_path, monkeypatch):  # noqa: F811
    """The chat UI's code for health and Status is generated from the description (suveryn-tracker#238): each
    answer is checked against it, and kept for the chat UI's tests."""
    from described import Checked
    from fastapi.testclient import TestClient
    from suveryn_api_gateway.app import create_app
    from suveryn_api_gateway.auth import Authenticator
    from suveryn_api_gateway.routes import status
    from suveryn_harness import LlamaServerClient, LLMSettings
    from test_api import fake_backend, unreachable_backend

    c, kc, _ = setup
    monkeypatch.setattr(status, "DATA_PATH", tmp_path)
    check, user, admin = Checked(c, "status"), as_user(kc, BOB), as_user(kc, ALICE, admin=True)

    monkeypatch.setattr(status, "_disk", lambda: (300 * 1024**3, 900 * 1024**3))  # not this machine's disk: room enough
    monkeypatch.setattr(status, "FRESH_S", 0)  # checked now, not what the monitor found when the app started

    def same_every_run(body):  # the moment a check was first seen failing
        for row in body["checks"]:
            row["since"] = row["since"] and "2026-11-22T09:00:00Z"

    assert check("GET", "/v1/admin/status", 401).json()["code"] == "auth.signed_out"
    assert check("GET", "/v1/admin/status", 403, keep="not_an_administrator", headers=user).json()["code"] == "request.forbidden"
    answer = check("GET", "/v1/admin/status", 200, keep="checks", same_every_run={"checked_at": "2026-11-22T09:00:05Z"},
                   tidy=same_every_run, headers=admin).json()
    assert [x["id"] for x in answer["checks"]] == ["answering", "reading", "signin", "data", "disk", "clock"]
    disk = answer["checks"][4]
    assert (disk["ok"], disk["since"], disk["free"], disk["total"]) == (True, None, 300 * 1024**3, 900 * 1024**3)

    # health is public: no sign-in, the same body with 200 and, while the model server isn't ready, with 503
    def health(transport, expected, keep):
        app = create_app(LlamaServerClient(LLMSettings(base_url="http://llm"), transport=transport), load_documents=False,
                         auth=Authenticator.disabled())
        with TestClient(app) as public:
            check.client = public
            return check("GET", "/health", expected, keep=keep).json()
    assert health(fake_backend(), 200, "ready")["status"] == "ok"
    assert health(fake_backend(health_status=503), 503, "loading")["backend"]["status"] == "loading"
    assert health(fake_backend(health_status=500), 503, "error")["backend"] == {"reachable": True, "status": "error", "url": None,
                                                                              "model": None, "detail": None}
    assert health(unreachable_backend(), 503, "unreachable")["backend"]["reachable"] is False
    check.kept.check()
    # not seen: what nobody planned for; and for Status, sign-in or the database down
    assert check.not_seen() == {("GET", "/health", 500), ("GET", "/v1/admin/status", 500), ("GET", "/v1/admin/status", 503)}
