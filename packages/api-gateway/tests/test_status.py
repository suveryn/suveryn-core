"""Administration › Status (docs/design/admin.md, artboards 30 and 39): five checks in plain words, counts only."""

from test_usage import ALICE, BOB, as_user, setup  # noqa: F401 - the fixture


def test_the_checks_are_for_administrators_and_say_since_when_one_fails(setup, tmp_path, monkeypatch):  # noqa: F811
    from suveryn_api_gateway.routes import status

    c, kc, _ = setup
    monkeypatch.setattr(status, "DATA_PATH", tmp_path)
    user, admin = as_user(kc, BOB), as_user(kc, ALICE, admin=True)
    assert c.get("/v1/admin/status", headers=user).status_code == 403
    body = c.get("/v1/admin/status", headers=admin).json()
    checks = {x["id"]: x for x in body["checks"]}
    assert list(checks) == ["answering", "reading", "signin", "data", "disk"]
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
    """Filip, 29 October: Status shows the version, without the installation having to set it."""
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
