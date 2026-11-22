"""The appliance's clock, kept right by the browsers of the people signed in (clock.py, decision, 30 October)."""

import json
import time

import pytest
from described import DESCRIBED, Kept, answer_is_described
from test_auth import sign_in
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


def test_an_administrator_sets_the_clock_to_their_pcs_time(setup, appliance, monkeypatch, caplog):  # noqa: F811
    caplog.set_level("WARNING")
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
    assert c.get(f"/v1/admin/clock/{rid}", headers=admin).json() == {"id": rid, "pending": False, "ok": True, "failure": None,
                                                                     "moved_ms": 95_000}
    c.get(f"/v1/admin/clock/{rid}", headers=admin)
    # VM regression 9c97d76, finding 5: "asked" at the request, and the appliance's answer once, not "set" before it acted
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("clock:")]
    assert lines == ["clock: an administrator asked to set the appliance's clock by +95.0 s",
                     "clock: the appliance's clock was set (moved by +95.0 s)"]
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


def test_reports_arriving_at_once_ask_for_one_nudge(appliance, monkeypatch):
    """External review, pass 8: reports at the same moment could all find the reports agreeing and all try to leave
    a request (without the lock: three tries here, one landing only because the file check was lucky). With the
    lock, one try; the others find the nudge just asked."""
    import threading
    c, now, asks = Clock(), 1_000_000.0, []
    real = clock.leave_request

    def slow(body):  # widen the window: each request takes a moment to write
        time.sleep(0.05)
        rid = real(body)
        asks.append(rid)
        return rid
    monkeypatch.setattr(clock, "leave_request", slow)
    c.report(BOB, False, 3000, 40, now)
    threads = [threading.Thread(target=c.report, args=(who, False, 3000, 40, now)) for who in (CARLA, "user-d", "user-e")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(asks) == 1 and asks[0]


def test_every_answer_of_the_clock_is_what_the_description_says(setup, appliance, monkeypatch):  # noqa: F811
    """The chat UI's code for the clock is generated from the description (suveryn-tracker#236): each answer the
    clock's operations give, the refusals too, is checked against it."""
    c, kc, _ = setup
    user, admin, body = as_user(kc, BOB), as_user(kc, ALICE, admin=True), {"offset_ms": -95_000, "rtt_ms": 40}
    seen, kept, RID = set(), Kept("clock"), "0123456789abcdef"

    def check(method, path, expected, at=None, keep=None, same_every_run=None, **request):
        r = c.request(method, at or path, **request)
        assert r.status_code == expected, f"{method} {at or path}: {r.status_code} {r.text}"
        answer_is_described(r, method, path)
        seen.add((method, path, expected))
        if keep:
            kept.keep(keep, r, **(same_every_run or {}))
        return r

    for method, path, at, sent in (("GET", "/v1/clock", None, {}), ("POST", "/v1/clock", None, {"json": body}),
                                   ("POST", "/v1/admin/clock", None, {"json": body}),
                                   ("GET", "/v1/admin/clock/{rid}", "/v1/admin/clock/0123456789abcdef", {})):
        assert check(method, path, 401, at, keep="signed_out" if path == "/v1/clock" and method == "GET" else None, **sent).json()["code"] == "auth.signed_out"
    check("GET", "/v1/clock", 200, keep="now", same_every_run={"now_ms": 1_795_000_000_000}, headers=user)
    check("POST", "/v1/clock", 204, keep="reported", json={"offset_ms": 2500, "rtt_ms": 30}, headers=user)
    invalid = check("POST", "/v1/clock", 422, keep="invalid", json={"offset_ms": "soon"}, headers=user).json()
    assert invalid["code"] == "request.invalid" and {e["loc"][-1] for e in invalid["errors"]} == {"offset_ms", "rtt_ms"}

    assert check("POST", "/v1/admin/clock", 403, keep="not_an_administrator", json=body, headers=user).json()["code"] == "request.forbidden"
    assert check("GET", "/v1/admin/clock/{rid}", 403, "/v1/admin/clock/0123456789abcdef", headers=user).json()["code"] == "request.forbidden"
    assert check("POST", "/v1/admin/clock", 422, keep="too_slow", json={**body, "rtt_ms": 3000}, headers=admin).json()["code"] == "clock.measurement_too_slow"
    assert check("POST", "/v1/admin/clock", 422, json={}, headers=admin).json()["code"] == "request.invalid"
    rid = check("POST", "/v1/admin/clock", 202, keep="asked", same_every_run={"id": RID}, json=body, headers=admin).json()["id"]
    assert check("POST", "/v1/admin/clock", 409, keep="busy", json=body, headers=admin).json()["code"] == "clock.busy"
    assert check("GET", "/v1/admin/clock/{rid}", 200, f"/v1/admin/clock/{rid}", "pending", {"id": RID}, headers=admin).json()["pending"]
    assert check("GET", "/v1/admin/clock/{rid}", 404, "/v1/admin/clock/not-an-id", "no_such_request", headers=admin).json()["code"] == "request.not_found"
    clock.RESULT.write_text(json.dumps({"id": rid, "kind": "set", "ok": False, "failure": {"code": "clock.synced"}}))
    refused = check("GET", "/v1/admin/clock/{rid}", 200, f"/v1/admin/clock/{rid}", "not_set", {"id": RID}, headers=admin).json()
    assert refused["ok"] is False and refused["failure"] == {"kind": "refused", "code": "clock.synced", "params": {}}
    clock.RESULT.write_text(json.dumps({"id": rid, "kind": "set", "ok": True, "moved_ms": 95_000}))
    assert check("GET", "/v1/admin/clock/{rid}", 200, f"/v1/admin/clock/{rid}", "set", {"id": RID}, headers=admin).json()["moved_ms"] == 95_000
    (appliance / "request.json").unlink()
    monkeypatch.setattr(clock, "time_server_keeps_it", lambda: True)
    c.app.state.clock = Clock()
    assert check("POST", "/v1/admin/clock", 409, keep="synced", json=body, headers=admin).json()["code"] == "clock.synced"
    monkeypatch.setattr(clock, "time_server_keeps_it", lambda: False)
    c.app.state.clock = Clock()
    monkeypatch.setattr(clock, "REQUESTS", appliance / "gone")
    assert check("POST", "/v1/admin/clock", 503, keep="unavailable", json=body, headers=admin).json()["code"] == "clock.unavailable"

    sign_in(c, kc)  # a browser's session: a change from another site's page is refused (app.py, require_sign_in)
    assert check("POST", "/v1/clock", 403, json=body, headers={"Origin": "https://elsewhere.example"}).json()["code"] == "request.forbidden"

    def broken(*_):
        raise RuntimeError("a document's words")
    monkeypatch.setattr(clock, "result_of", broken)
    unplanned = check("GET", "/v1/admin/clock/{rid}", 500, f"/v1/admin/clock/{RID}", "unplanned", {"ref": "7F3K-92QD"}, headers=admin)
    assert unplanned.json()["code"] == "system.internal" and "document" not in unplanned.text
    kept.check()

    # every status the description gives the clock's operations was seen here, but: what nobody planned for, seen on
    # one; sign-in or the database down, and sign-in turned off for another machine, which no operation decides for
    # itself (test_auth.py, test_problems.py); and the 422 FastAPI gives every operation with a parameter, which an
    # id in the address, any text, never gets
    described = {(method.upper(), path, int(status)) for path, by_method in DESCRIBED["paths"].items()
                 for method, op in by_method.items() if op["tags"] == ["clock"] for status in op["responses"]}
    assert described - seen == {
        ("GET", "/v1/clock", 500), ("POST", "/v1/clock", 500), ("POST", "/v1/admin/clock", 500),
        ("GET", "/v1/clock", 403), ("GET", "/v1/clock", 503), ("POST", "/v1/clock", 503), ("GET", "/v1/admin/clock/{rid}", 503),
        ("GET", "/v1/admin/clock/{rid}", 422)}
