"""suveryn-tracker#7: token usage per user, an administrator's view of the office, and the rates.

The API tests use an in-memory store with the same methods as ``UsageStore``; the store tests at
the end run against a real PostgreSQL and are skipped unless SUVERYN_TEST_DATABASE_URL is set.
"""

import os
from urllib.parse import parse_qs, urlsplit
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
from suveryn_engine import LlamaServerClient, LLMSettings, UsageRecord
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
    assert (body["input_per_million"], body["currency"], body["updated_by"]) == ("2.5", "EUR", ALICE)
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
