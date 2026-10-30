"""The appliance's clock, kept right by the browsers of the people signed in (clock.py, Filip, 30 October)."""

import json
import time

import pytest
from test_usage import ALICE, BOB, as_user, setup  # noqa: F401 - the fixture

from suveryn_api_gateway import clock
from suveryn_api_gateway.clock import Clock

CARLA = "user-c"


@pytest.fixture
def appliance(tmp_path, monkeypatch):
    """The appliance's folder for clock requests, and its answer file."""
    folder = tmp_path / "clock-requests"
    folder.mkdir()
    monkeypatch.setattr(clock, "REQUESTS", folder)
    monkeypatch.setattr(clock, "RESULT", tmp_path / "result.json")
    return folder


def asked(folder) -> dict | None:
    path = folder / "request.json"
    return json.loads(path.read_text()) if path.exists() else None


def test_one_person_alone_moves_nothing_two_who_agree_nudge_it(appliance):
    c, now = Clock(), 1_000_000.0
    assert c.report(BOB, False, 4000, 40, now) is None and asked(appliance) is None  # one person, not an administrator
    assert c.report(CARLA, False, 4600, 30, now + 5) == 4300  # two agree: the middle of their reports
    assert asked(appliance)["kind"] == "nudge" and asked(appliance)["offset_ms"] == 4300
    assert c.reports == {}  # the next reports measure the clock while it is moved


def test_an_administrator_alone_is_enough(appliance):
    assert Clock().report(ALICE, True, -3000, 50, 1_000_000.0) == -3000
    assert asked(appliance)["offset_ms"] == -3000


@pytest.mark.parametrize("reports", [
    [(BOB, 4000), (CARLA, 9000)],         # they disagree by more than two seconds
    [(BOB, 200), (CARLA, 300)],           # too little to move the clock for
    [(BOB, 90_000), (CARLA, 90_500)],     # too much: an administrator's choice on Status
])
def test_nothing_is_asked_unless_the_reports_agree_on_a_small_difference(appliance, reports):
    c = Clock()
    for who, offset in reports:
        assert c.report(who, False, offset, 40, 1_000_000.0) is None
    assert asked(appliance) is None


def test_a_slow_measurement_an_old_one_a_time_server_and_the_hour_between_nudges(appliance, monkeypatch):
    c, now = Clock(), 1_000_000.0
    assert c.report(ALICE, True, 3000, 1500, now) is None and c.reports == {}  # a round trip too slow to say anything
    c.report(BOB, False, 3000, 40, now)
    assert c.report(CARLA, False, 3000, 40, now + clock.KEPT_S + 1) is None  # Bob's is a day old
    assert c.report(BOB, False, 3000, 40, now + clock.KEPT_S + 2) == 3000
    (appliance / "request.json").unlink()
    c.report(BOB, False, 2000, 40, now + clock.KEPT_S + 60)
    assert c.report(CARLA, False, 2000, 40, now + clock.KEPT_S + 61) is None  # within the hour of the last nudge
    monkeypatch.setattr(clock, "time_server_keeps_it", lambda: True)
    synced = Clock()
    synced.report(BOB, False, 3000, 40, now)
    assert synced.report(CARLA, False, 3000, 40, now) is None and asked(appliance) is None


def test_without_the_appliances_folder_nothing_is_asked():
    c = Clock()  # conftest: no folder (a development machine)
    c.report(BOB, False, 3000, 40, 1_000_000.0)
    assert c.report(CARLA, False, 3000, 40, 1_000_000.0) is None


def test_signed_in_browsers_measure_and_report(setup, appliance):  # noqa: F811
    c, kc, _ = setup
    assert c.get("/v1/clock").status_code == 401
    r = c.get("/v1/clock", headers=as_user(kc, BOB))
    assert r.status_code == 200 and abs(r.json()["now_ms"] - time.time() * 1000) < 5000 and r.headers["cache-control"] == "no-store"
    assert c.post("/v1/clock", json={"offset_ms": 2500, "rtt_ms": 30}, headers=as_user(kc, BOB)).status_code == 204
    assert asked(appliance) is None  # Bob alone
    assert c.post("/v1/clock", json={"offset_ms": 2700, "rtt_ms": 30}, headers=as_user(kc, ALICE, admin=True)).status_code == 204
    assert asked(appliance) == {"id": asked(appliance)["id"], "kind": "nudge", "offset_ms": 2600}
    assert c.post("/v1/clock", json={"offset_ms": 400 * 24 * 3600 * 1000, "rtt_ms": 30}, headers=as_user(kc, BOB)).status_code == 422


def test_an_administrator_sets_the_clock_to_their_pcs_time(setup, appliance, monkeypatch):  # noqa: F811
    c, kc, _ = setup
    admin, body = as_user(kc, ALICE, admin=True), {"offset_ms": -95_000, "rtt_ms": 40}
    assert c.post("/v1/admin/clock", json=body, headers=as_user(kc, BOB)).status_code == 403
    r = c.post("/v1/admin/clock", json=body, headers=admin)
    assert r.status_code == 202 and r.json()["pending"]
    rid = r.json()["id"]
    assert asked(appliance) == {"id": rid, "kind": "set", "offset_ms": -95_000}
    assert c.post("/v1/admin/clock", json=body, headers=admin).status_code == 409  # the last one is still there
    assert c.get(f"/v1/admin/clock/{rid}", headers=admin).json()["pending"]
    clock.RESULT.write_text(json.dumps({"id": rid, "kind": "set", "ok": True, "moved_ms": 95_000}))
    assert c.get(f"/v1/admin/clock/{rid}", headers=admin).json() == {"id": rid, "pending": False, "ok": True, "error": None,
                                                                     "moved_ms": 95_000}
    (appliance / "request.json").unlink()
    assert c.post("/v1/admin/clock", json={**body, "rtt_ms": 3000}, headers=admin).status_code == 422
    monkeypatch.setattr(clock, "time_server_keeps_it", lambda: True)
    c.app.state.clock = Clock()
    assert c.post("/v1/admin/clock", json=body, headers=admin).status_code == 409 and asked(appliance) is None


def test_set_without_the_appliances_folder_is_not_available(setup):  # noqa: F811
    c, kc, _ = setup
    r = c.post("/v1/admin/clock", json={"offset_ms": 95_000, "rtt_ms": 40}, headers=as_user(kc, ALICE, admin=True))
    assert r.status_code == 503


def test_status_says_how_far_off_the_clock_is_or_that_a_time_server_keeps_it(setup, monkeypatch):  # noqa: F811
    from suveryn_api_gateway.routes import status

    c, kc, _ = setup
    monkeypatch.setattr(status, "FRESH_S", 0)
    admin = as_user(kc, ALICE, admin=True)
    check = lambda: next(x for x in c.get("/v1/admin/status", headers=admin).json()["checks"] if x["id"] == "clock")  # noqa: E731
    assert check()["ok"] and check()["offset_ms"] is None  # nothing measured yet
    c.post("/v1/clock", json={"offset_ms": 25_000, "rtt_ms": 40}, headers=as_user(kc, BOB))
    assert not check()["ok"] and check()["offset_ms"] == 25_000  # codes fail from about 30 seconds
    monkeypatch.setattr(clock, "time_server_keeps_it", lambda: True)
    c.app.state.clock._synced = (0.0, None)
    assert check()["ok"] and check()["synced"] is True and check()["offset_ms"] is None
