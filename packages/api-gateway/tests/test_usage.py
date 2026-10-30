"""suveryn-tracker#7: token usage per user, an administrator's view of the office, and the rates.

The API tests use an in-memory store with the same methods as ``UsageStore``; the store tests at
the end run against a real PostgreSQL and are skipped unless SUVERYN_TEST_DATABASE_URL is set.
"""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient
from suveryn_api_gateway.app import ADMIN_ROLE, create_app
from suveryn_api_gateway.auth import Authenticator, OIDCProvider
from suveryn_api_gateway.usage import (
    AdminUsageReport,
    Rates,
    UsageReport,
    UsageSettings,
    UsageStore,
    UsageTotals,
    UserUsage,
    cost,
    parse_range,
    step_for,
)
from suveryn_harness import LlamaServerClient, LLMSettings, UsageRecord
from test_auth import SETTINGS, FakeKeycloak, sign_in
from test_documents import llm_transport

ALICE, BOB = "user-a", "user-b"
CHAT = {"messages": [{"role": "user", "content": "Wat is de koopprijs?"}]}


class FakeUsage:
    """In-memory stand-in for ``UsageStore``: records calls, answers with fixed reports."""

    def __init__(self):
        self.records: list[UsageRecord] = []
        self.users: dict[str, tuple[str, str]] = {}
        self.asked: list[tuple] = []
        self._rates = Rates(input_per_million=Decimal(3), output_per_million=Decimal(15))

    def record(self, r):
        self.records.append(r)

    def purge(self):
        return 0

    def remember_user(self, sub, username, name):
        self.users[sub] = (username, name)

    def report(self, start, end, owner):
        self.asked.append(("report", owner))
        mine = [r for r in self.records if owner is None or r.user == owner]
        totals = UsageTotals(requests=len(mine), prompt_tokens=sum(r.prompt_tokens for r in mine),
                             completion_tokens=sum(r.completion_tokens for r in mine),
                             total_tokens=sum(r.total_tokens for r in mine))
        return UsageReport(start=start, end=end, step="1 hour", totals=totals, series=[], by_kind={})

    def admin_report(self, start, end):
        self.asked.append(("admin_report",))
        base = self.report(start, end, None)
        return AdminUsageReport(**base.model_dump(), rates=self._rates, cost=Decimal("0.01"),
                                per_user=[UserUsage(user_id=u, username=n[0], name=n[1], totals=base.totals) for u, n in self.users.items()])

    def rates(self):
        return self._rates

    def set_rates(self, rates, by):
        self._rates = rates.model_copy(update={"updated_by": by})
        return self._rates


@pytest.fixture
def setup():
    kc, store = FakeKeycloak(), FakeUsage()
    auth = Authenticator(SETTINGS, OIDCProvider(SETTINGS, transport=httpx.MockTransport(kc.handler)))
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"),
                            transport=llm_transport([], usage={"prompt_tokens": 1200, "completion_tokens": 85}))
    with TestClient(create_app(llm, load_documents=False, auth=auth, usage=store)) as c:
        yield c, kc, store


def as_user(kc: FakeKeycloak, sub: str, admin: bool = False) -> dict:
    claims = {"sub": sub, "preferred_username": sub, "realm_access": {"roles": [ADMIN_ROLE] if admin else []}}
    return {"Authorization": f"Bearer {kc.tokens(over=claims)['access_token']}"}


def test_every_question_is_counted_for_whoever_asked_it(setup):
    c, kc, store = setup
    assert c.post("/v1/chat", json=CHAT, headers=as_user(kc, ALICE)).status_code == 200
    with c.stream("POST", "/v1/chat", json={**CHAT, "stream": True}, headers=as_user(kc, BOB)) as r:
        list(r.iter_lines())
    assert [(r.user, r.kind, r.total_tokens) for r in store.records] == [(ALICE, "chat", 1285), (BOB, "chat", 1285)]
    assert set(store.users) == {ALICE, BOB}  # names kept for the administrator's table


def test_users_see_only_their_own_usage(setup):
    c, kc, store = setup
    r = c.get("/v1/usage", headers=as_user(kc, BOB))
    assert r.status_code == 200 and store.asked == [("report", BOB)]


def test_the_office_view_and_rates_are_for_administrators_only(setup):
    c, kc, store = setup
    user, admin = as_user(kc, BOB), as_user(kc, ALICE, admin=True)
    assert c.get("/v1/admin/usage", headers=user).status_code == 403
    assert c.get("/v1/admin/usage/rates", headers=user).status_code == 403
    assert c.put("/v1/admin/usage/rates", json={"input_per_million": 1, "output_per_million": 1}, headers=user).status_code == 403
    assert store.asked == []  # nothing was read for a non-administrator
    assert c.get("/v1/admin/usage", headers=admin).status_code == 200
    new = {"input_per_million": "2.5", "output_per_million": "10", "currency": "EUR"}
    body = c.put("/v1/admin/usage/rates", json=new, headers=admin).json()
    assert (body["input_per_million"], body["currency"], body["updated_by"]) == ("2.5", "EUR", "Test Notaris")  # the name (round 4, finding 4)
    for bad in ({"input_per_million": -1, "output_per_million": 1}, {"input_per_million": 1, "output_per_million": 1, "currency": "euro"}):
        assert c.put("/v1/admin/usage/rates", json=bad, headers=admin).status_code == 422


@pytest.mark.parametrize("roles, admin", [([], False), ([ADMIN_ROLE], True), (["offline_access"], False)])
def test_me_says_whether_the_user_is_an_administrator(setup, roles, admin):
    c, kc, _ = setup
    assert sign_in(c, kc, realm_access={"roles": roles}).status_code == 303
    assert c.get("/auth/me").json()["admin"] is admin


def test_admin_role_is_read_from_the_access_token_as_keycloak_issues_it(setup):
    """Keycloak puts realm roles in the access token only; the ID token has none."""
    c, kc, _ = setup
    r = c.get("/auth/login", follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
    kc.codes["code-1"] = {"nonce": q["nonce"], "challenge": q["code_challenge"],
                          "access_over": {"realm_access": {"roles": [ADMIN_ROLE]}}}
    assert c.get("/auth/callback", params={"code": "code-1", "state": q["state"]}, follow_redirects=False).status_code == 303
    assert c.get("/auth/me").json()["admin"] is True
    assert c.get("/v1/admin/usage").status_code == 200


def test_range_validation(setup):
    c, kc, _ = setup
    alice = as_user(kc, ALICE)
    assert c.get("/v1/usage", params={"start": "2026-10-10T10:00:00Z", "end": "2026-10-10T09:00:00Z"}, headers=alice).status_code == 422
    assert c.get("/v1/usage", params={"start": "2026-10-10T10:00:00"}, headers=alice).status_code == 422  # no time zone
    assert c.get("/v1/usage", params={"start": "2016-01-01T00:00:00Z"}, headers=alice).status_code == 422  # over five years


def test_without_a_database_usage_is_unavailable_but_answers_work():
    llm = LlamaServerClient(LLMSettings(base_url="http://llm"), transport=llm_transport([]))
    with TestClient(create_app(llm, load_documents=False, auth=Authenticator.disabled())) as c:
        assert c.get("/v1/usage").status_code == 503
        assert c.get("/health").json()["usage"] == {"status": "unavailable", "detail": None}
        assert c.post("/v1/chat", json=CHAT).status_code == 200


def test_buckets_cost_and_ranges():
    assert step_for(timedelta(hours=1))[1] == "5 minutes" and step_for(timedelta(days=1))[1] == "1 hour"
    assert step_for(timedelta(days=30))[1] == "1 day" and step_for(timedelta(days=365))[1] == "7 days"
    rates = Rates(input_per_million=Decimal(3), output_per_million=Decimal(15))
    assert cost(1_000_000, 100_000, rates) == Decimal("4.50")
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    assert parse_range(None, None, now) == (now - timedelta(days=1), now)


# ------------------------------------------------------------------ against a real PostgreSQL

URL = os.environ.get("SUVERYN_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not URL, reason="SUVERYN_TEST_DATABASE_URL not set")
TEST_USERS = ("usage-test-a", "usage-test-b")


@pytest.fixture
def store():
    s = UsageStore(UsageSettings(database_url=URL))
    clean = "DELETE FROM token_usage WHERE owner = ANY(%s); DELETE FROM usage_users WHERE sub = ANY(%s)"
    for q in clean.split("; "):
        s._execute(q, (list(TEST_USERS),))
    saved = s._execute("SELECT input_per_million, output_per_million, currency, updated_at, updated_by FROM usage_rates").fetchone()
    yield s
    for q in clean.split("; "):
        s._execute(q, (list(TEST_USERS),))
    s._execute("UPDATE usage_rates SET input_per_million = %s, output_per_million = %s, currency = %s, updated_at = %s,"
               " updated_by = %s WHERE id = 1", saved)  # exactly as before, including who changed it
    s.close()


def put(s: UsageStore, user: str, at: datetime, prompt: int, completion: int, kind: str = "chat") -> None:
    s.record(UsageRecord(user=user, kind=kind, model="test-model", prompt_tokens=prompt, completion_tokens=completion))
    s._execute("UPDATE token_usage SET at = %s WHERE id = (SELECT max(id) FROM token_usage)", (at,))


@needs_db
def test_store_reports_own_usage_in_local_days(store):
    a, b = TEST_USERS
    # 22:30 UTC on 9 October is 00:30 on 10 October in Brussels (CEST): it counts for the 10th.
    put(store, a, datetime(2026, 10, 9, 22, 30, tzinfo=UTC), 1000, 100)
    put(store, a, datetime(2026, 10, 10, 9, 0, tzinfo=UTC), 2000, 200, kind="summary")
    put(store, b, datetime(2026, 10, 10, 9, 0, tzinfo=UTC), 5000, 500)
    start, end = datetime(2026, 10, 8, 22, tzinfo=UTC), datetime(2026, 10, 10, 22, tzinfo=UTC)  # 9 and 10 Oct, local
    with_b_excluded = store.report(start, end + timedelta(days=5), owner=a)  # > 2 days: daily buckets
    assert with_b_excluded.totals == UsageTotals(requests=2, prompt_tokens=3000, completion_tokens=300, total_tokens=3300)
    brussels = ZoneInfo("Europe/Brussels")  # buckets are instants; each starts at local midnight
    days = {bucket.start.astimezone(brussels).date().isoformat(): bucket.total_tokens for bucket in with_b_excluded.series}
    assert all(bucket.start.astimezone(brussels).hour == 0 for bucket in with_b_excluded.series)
    assert days["2026-10-09"] == 0 and days["2026-10-10"] == 3300  # zero-filled, in local days
    assert set(with_b_excluded.by_kind) == {"chat", "summary"}


@needs_db
def test_store_admin_report_per_user_with_cost(store):
    a, b = TEST_USERS
    store.remember_user(a, "notaris.a", "Notaris A")
    at = datetime.now(UTC) - timedelta(minutes=5)
    put(store, a, at, 1_000_000, 100_000)
    put(store, b, at, 10, 1)
    store.set_rates(Rates(input_per_million=Decimal(3), output_per_million=Decimal(15)), "test")
    rep = store.admin_report(at - timedelta(hours=1), at + timedelta(hours=1))
    mine = {u.user_id: u for u in rep.per_user if u.user_id in TEST_USERS}
    assert mine[a].username == "notaris.a" and mine[a].totals.total_tokens == 1_100_000 and mine[a].cost == Decimal("4.50")
    assert mine[b].username is None  # never asked through the gateway: no name known
    assert [u.user_id for u in rep.per_user].index(a) < [u.user_id for u in rep.per_user].index(b)  # most tokens first
    assert rep.step == "5 minutes" and rep.cost >= Decimal("4.50")


@needs_db
def test_store_keeps_raw_usage_for_its_period_then_only_the_offices_monthly_totals(store):
    """Audit of 21 October 2026, finding 10 (the owner's decision): raw rows for 24 months, then totals."""
    a, b = TEST_USERS
    store._execute("DELETE FROM usage_monthly WHERE model = 'test-model'")
    now = datetime.now(UTC)
    old = (now - timedelta(days=31 * 30)).replace(day=15, hour=12)  # about 30 months ago, mid-month
    put(store, a, old, 1000, 100)
    put(store, a, old + timedelta(hours=1), 3000, 300)
    put(store, a, now - timedelta(days=3), 500, 50)
    store.remember_user(a, "notaris.a", "Notaris A")
    store.remember_user(b, "notaris.b", "Notaris B")  # nothing recent: the name goes too
    store._execute("UPDATE usage_users SET seen_at = %s WHERE sub = %s", (old, b))
    assert store.purge() >= 2
    left = store._execute("SELECT at FROM token_usage WHERE owner = %s", (a,)).fetchall()
    assert len(left) == 1 and left[0][0] > store.cutoff()
    month = store._execute("SELECT kind, requests, prompt_tokens, completion_tokens FROM usage_monthly WHERE model = 'test-model'").fetchall()
    assert month == [("chat", 2, 4000, 400)]  # no person in it
    names = {r[0] for r in store._execute("SELECT sub FROM usage_users WHERE sub = ANY(%s)", (list(TEST_USERS),)).fetchall()}
    assert names == {a}
    assert store.purge() == 0 or store._execute(
        "SELECT requests FROM usage_monthly WHERE model = 'test-model'").fetchone()[0] == 2  # nothing counted twice
    office = store.report(now - timedelta(days=4 * 365), now, owner=None)
    assert office.totals_only_before == store.cutoff()
    assert office.by_kind["chat"].prompt_tokens >= 4500  # the old months' totals, and the recent row
    assert sum(x.prompt_tokens for x in office.series) == office.totals.prompt_tokens
    own = store.report(now - timedelta(days=4 * 365), now, owner=a)
    assert own.totals.prompt_tokens == 500  # nobody's own usage before the cutoff
    store._execute("DELETE FROM usage_monthly WHERE model = 'test-model'")


def test_the_backups_status_is_for_administrators_and_read_as_written(setup, tmp_path, monkeypatch):
    """suveryn-tracker#33: what the appliance's backup service recorded, checked, never more."""
    import json

    from suveryn_api_gateway.routes import backups

    c, kc, _ = setup
    monkeypatch.setattr(backups, "STATUS", tmp_path / "status.json")
    monkeypatch.setattr(backups, "SETTINGS", tmp_path / "backups.json")
    user, admin = as_user(kc, BOB), as_user(kc, ALICE, admin=True)
    assert c.get("/v1/admin/backups", headers=user).status_code == 403
    assert c.get("/v1/admin/backups", headers=admin).json()["available"] is False  # never run, or not an appliance
    (tmp_path / "status.json").write_text(json.dumps({
        "configured": True, "target": "usb", "retention_days": 30, "last_attempt": "2026-10-23T02:41:07Z",
        "last_success": {"at": "2026-10-22T02:39:00Z", "file": "suveryn-backup_x_20261022T023900Z.tar.zst.age",
                         "size": 123456, "on_target": 12, "oldest": "2026-09-23T02:31:00Z", "seconds": 40},
        "last_error": {"at": "2026-10-23T02:41:07Z", "step": "target", "message": "the backup disk isn't connected"}}))
    body = c.get("/v1/admin/backups", headers=admin).json()
    assert body["available"] and body["configured"] and body["target"] == "usb" and body["retention_days"] == 30
    assert body["last_success"] == {"at": "2026-10-22T02:39:00Z", "size": 123456, "on_target": 12, "oldest": "2026-09-23T02:31:00Z",
                                    "disk": None}
    assert body["last_error"]["step"] == "target" and "file" not in body["last_success"]
    (tmp_path / "status.json").write_text("not json")
    assert c.get("/v1/admin/backups", headers=admin).json() == {**dict.fromkeys(body, None), "available": False, "configured": False,
                                                               "key_testing": False}


def test_the_recovery_key_is_passed_to_the_backup_service_for_a_test_and_its_result_shown(setup, tmp_path, monkeypatch):
    """Review of the backup strategy: the appliance can't read its own backups, so the administrator tests
    the key. The gateway checks it is a key file, leaves it with a request for the backup service (0600,
    the request last), and shows the result; never the key."""
    import json
    import stat

    from suveryn_api_gateway.routes import backups

    c, kc, _ = setup
    drop = tmp_path / "drop"
    monkeypatch.setattr(backups, "STATUS", tmp_path / "status.json")
    monkeypatch.setattr(backups, "KEY_TEST_RESULT", tmp_path / "key-test.json")
    monkeypatch.setattr(backups, "KEY_TEST_DROP", drop)
    user, admin = as_user(kc, BOB), as_user(kc, ALICE, admin=True)
    key = "AGE-SECRET-KEY-1" + "Q" * 58
    file = f"# Sūveryn backup recovery key\n# created: 2026-10-20\n{key}\n".encode()
    post = lambda body, who=admin: c.post("/v1/admin/backups/key-test", content=body, headers={**who, "Content-Type": "application/octet-stream"})
    assert post(file, user).status_code == 403
    assert post(file).status_code == 503  # not an appliance: no backup service to ask
    drop.mkdir()
    for bad in (b"", b"not a key", file + file, b"AGE-SECRET-KEY-1" + b"Q" * 58 + b"X", b"x" * 5000):
        assert post(bad).status_code == 415
    assert post(file).status_code == 202
    assert (drop / "key").read_text() == key + "\n" and stat.S_IMODE((drop / "key").stat().st_mode) == 0o600
    assert (drop / "request").exists() and post(file).status_code == 409  # one at a time
    (tmp_path / "status.json").write_text(json.dumps({"configured": True}))
    assert c.get("/v1/admin/backups", headers=admin).json()["key_testing"] is True
    (drop / "request").unlink()
    (tmp_path / "key-test.json").write_text(json.dumps({"at": "2026-10-26T10:00:00Z", "ok": False, "step": "decrypt",
                                                        "message": "this isn't this appliance's recovery key"}))
    body = c.get("/v1/admin/backups", headers=admin).json()
    assert body["key_testing"] is False and body["key_test"] == {"at": "2026-10-26T10:00:00Z", "ok": False, "created": None, "step": "decrypt"}
    assert key not in json.dumps(body)


def test_the_backup_settings_are_shown_and_changed_through_the_backup_service(setup, tmp_path, monkeypatch):
    """Administration › Backups (docs/design/admin.md, artboard 36): the settings as saved, never the share's
    password; and every change as a request the appliance's backup service acts on, one at a time."""
    import json
    import stat
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from suveryn_api_gateway.routes import backups

    c, kc, _ = setup
    monkeypatch.setattr(backups, "appliance_zone", lambda: ZoneInfo("Europe/Brussels"))  # the machine's own zone
    folder = tmp_path / "requests"
    for name, value in (("STATUS", tmp_path / "status.json"), ("SETTINGS", tmp_path / "backups.json"),
                        ("SHARE_SECRET", tmp_path / "share.secret"), ("REQUESTS", folder),
                        ("REQUEST_RESULT", tmp_path / "request-result.json")):
        monkeypatch.setattr(backups, name, value)
    user, admin = as_user(kc, BOB), as_user(kc, ALICE, admin=True)
    recipient = "age1" + "q" * 58
    (tmp_path / "backups.json").write_text(json.dumps({"target": "share", "protocol": "smb", "address": "//nas.office.lan/b",
                                                       "user": "backup", "retention_days": 90, "hour": 23, "recipient": recipient}))
    (tmp_path / "share.secret").write_text("not-a-real-password")
    s = c.get("/v1/admin/backups", headers=admin).json()["settings"]
    assert s["target"] == "share" and s["address"] == "//nas.office.lan/b" and s["has_password"] is True and s["hour"] == 23
    assert "not-a-real-password" not in json.dumps(s)
    local = datetime.strptime(s["next_run"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Brussels"))
    assert (local.hour, local.minute) == (23, 0)
    ask = lambda body, who=admin: c.post("/v1/admin/backups/requests", json=body, headers=who)  # noqa: E731
    assert ask({"kind": "run"}, user).status_code == 403
    assert ask({"kind": "run"}).status_code == 503  # not an appliance: no backup service
    folder.mkdir()
    settings = {"kind": "settings", "target": "share", "protocol": "smb", "address": "//nas.office.lan/b", "user": "backup",
                "password": "another-password", "retention_days": 30, "hour": 1}
    r = ask(settings)
    assert r.status_code == 202 and r.json()["pending"] is True
    rid = r.json()["id"]
    left = folder / "request.json"
    assert json.loads(left.read_text()) == {"id": rid, **settings, "keep_password": False} and stat.S_IMODE(left.stat().st_mode) == 0o600
    assert ask({"kind": "disks"}).status_code == 409  # one at a time
    assert c.get(f"/v1/admin/backups/requests/{rid}", headers=admin).json()["pending"] is True
    left.unlink()  # the backup service took it, and answered
    (tmp_path / "request-result.json").write_text(json.dumps({"id": rid, "kind": "settings", "ok": False,
                                                              "errors": {"address": "address"}}))
    answer = c.get(f"/v1/admin/backups/requests/{rid}", headers=admin).json()
    assert answer["ok"] is False and answer["errors"] == {"address": "address"} and answer["pending"] is False
    assert ask({**settings, "hour": 24}).status_code == 422 and ask({**settings, "retention_days": 7}).status_code == 422
    assert ask({"kind": "settings", "target": "usb"}).status_code == 422  # no retention or hour
    rid = ask({"kind": "disks", "password": "never-passed-on"}).json()["id"]
    assert json.loads(left.read_text()) == {"id": rid, "kind": "disks"}
    left.unlink()
    (tmp_path / "request-result.json").write_text(json.dumps({"id": rid, "ok": True, "disks": [
        {"id": "usb-Extreme_SER1", "name": "Extreme", "size_bytes": 10**12}, {"id": "../../etc", "name": "x"}]}))
    assert c.get(f"/v1/admin/backups/requests/{rid}", headers=admin).json()["disks"] == [
        {"id": "usb-Extreme_SER1", "name": "Extreme", "size_bytes": 10**12}]


def test_the_next_backup_is_given_in_the_appliances_own_zone(monkeypatch, tmp_path):
    """VM check of 28 October, finding 5: the backup tool runs on the machine's time, so the page must too."""
    import json
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from suveryn_api_gateway.routes import backups

    monkeypatch.setattr(backups, "SETTINGS", tmp_path / "backups.json")
    (tmp_path / "backups.json").write_text(json.dumps({"target": "usb", "disk": "usb-X_1", "retention_days": 30, "hour": 3,
                                                       "recipient": "age1" + "q" * 58}))
    now = datetime(2026, 10, 28, 20, 0, tzinfo=ZoneInfo("UTC"))
    monkeypatch.setattr(backups, "appliance_zone", lambda: ZoneInfo("UTC"))
    assert backups.read_settings(now).next_run == "2026-10-29T03:00:00Z"
    monkeypatch.setattr(backups, "appliance_zone", lambda: ZoneInfo("Europe/Brussels"))
    assert backups.read_settings(now).next_run == "2026-10-29T02:00:00Z"
    monkeypatch.undo()  # the real appliance_zone, with TZ set as systemd may set it
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert str(backups.appliance_zone()) == "Asia/Tokyo"
