"""Token usage: storage and reports (suveryn-tracker#7, development context §5.3).

The engine reports every model call's counts (``suveryn_engine.usage``); this module stores them,
one raw row per call, in PostgreSQL (``token_usage``), and answers two questions:

- a user's own usage over a time range (``report(owner=...)``): nobody sees a colleague's;
- the office's usage for administrators (``report(owner=None, per_user=True)``): totals, the same
  per user, and a notional cloud cost.

Design, as decided in §5.3: one table, raw rows, kept indefinitely; no rollups. A notary office
makes a few hundred calls a day, so ``date_bin`` + ``GROUP BY`` over raw rows stays fast for years.
Only counts are stored: who (Keycloak user id), when, kind, model and token counts; never text.
Usernames for the administrator's table are kept separately (``usage_users``), updated when a
user asks a question. Nothing here limits anyone: usage is informational.

The notional cost uses an administrator-editable rate per million input and output tokens
(``usage_rates``), defaulting to a comparable cloud model's published price: no hardware or power
cost is modelled.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, Field
from suveryn_engine import UsageRecord

from .db import PgStore

# The published price of a comparable large cloud model (USD per million tokens, October 2026).
DEFAULT_RATES = (Decimal(3), Decimal(15), "USD")
MAX_SPAN = timedelta(days=5 * 366)
ORIGIN = datetime(2000, 1, 3)  # a Monday: weekly buckets start on Mondays

SCHEMA = """
CREATE TABLE IF NOT EXISTS token_usage (
    id                 bigserial PRIMARY KEY,
    owner              text NOT NULL,
    at                 timestamptz NOT NULL DEFAULT now(),
    kind               text NOT NULL,
    model              text NOT NULL,
    prompt_tokens      integer NOT NULL,
    completion_tokens  integer NOT NULL,
    total_tokens       integer NOT NULL
);
CREATE INDEX IF NOT EXISTS token_usage_at ON token_usage (at);
CREATE INDEX IF NOT EXISTS token_usage_owner_at ON token_usage (owner, at);
CREATE TABLE IF NOT EXISTS usage_users (
    sub       text PRIMARY KEY,
    username  text NOT NULL,
    name      text NOT NULL,
    seen_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS usage_rates (
    id                  smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    input_per_million   numeric(12, 4) NOT NULL,
    output_per_million  numeric(12, 4) NOT NULL,
    currency            text NOT NULL,
    updated_at          timestamptz NOT NULL DEFAULT now(),
    updated_by          text
);
"""


@dataclass(frozen=True)
class UsageSettings:
    database_url: str = ""
    timezone: str = "Europe/Brussels"  # days and weeks in reports follow the office's local time

    @classmethod
    def from_env(cls) -> "UsageSettings":
        return cls(database_url=os.environ.get("SUVERYN_DATABASE_URL", ""),
                   timezone=os.environ.get("SUVERYN_TIMEZONE", cls.timezone))


class UsageTotals(BaseModel):
    requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class UsageBucket(UsageTotals):
    start: datetime


class Rates(BaseModel):
    """Notional cost per million tokens, as on a comparable cloud API (admin-editable)."""

    input_per_million: Decimal = Field(ge=0, le=10_000, decimal_places=4)
    output_per_million: Decimal = Field(ge=0, le=10_000, decimal_places=4)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    updated_at: datetime | None = None
    updated_by: str | None = None


class UserUsage(BaseModel):
    user_id: str
    username: str | None
    name: str | None
    totals: UsageTotals
    cost: Decimal | None = None


class UsageReport(BaseModel):
    """Usage between ``start`` and ``end``: totals, a series in ``step`` buckets (local time), per kind."""

    start: datetime
    end: datetime
    step: str  # "5 minutes", "1 hour", "1 day", "7 days" or "30 days"
    totals: UsageTotals
    series: list[UsageBucket]
    by_kind: dict[str, UsageTotals]


class AdminUsageReport(UsageReport):
    per_user: list[UserUsage]
    rates: Rates
    cost: Decimal  # notional: what the office's usage would have cost at ``rates``


def step_for(span: timedelta) -> tuple[timedelta, str]:
    """Bucket size for a range: a few dozen bars, whatever the range."""
    for limit, step, label in ((timedelta(hours=3), timedelta(minutes=5), "5 minutes"),
                               (timedelta(days=2), timedelta(hours=1), "1 hour"),
                               (timedelta(days=92), timedelta(days=1), "1 day"),
                               (timedelta(days=732), timedelta(days=7), "7 days")):
        if span <= limit:
            return step, label
    return timedelta(days=30), "30 days"


def cost(prompt_tokens: int, completion_tokens: int, rates: Rates) -> Decimal:
    raw = (Decimal(prompt_tokens) * rates.input_per_million + Decimal(completion_tokens) * rates.output_per_million) / 1_000_000
    return raw.quantize(Decimal("0.01"))


def _totals(row) -> UsageTotals:
    n, p, c = (int(x or 0) for x in row)
    return UsageTotals(requests=n, prompt_tokens=p, completion_tokens=c, total_tokens=p + c)


class UsageStore(PgStore):
    """``token_usage`` and friends in PostgreSQL. Creates its tables on connect."""

    schema = SCHEMA

    def __init__(self, settings: UsageSettings):
        super().__init__(settings.database_url)
        self.tz = settings.timezone
        self._execute("INSERT INTO usage_rates (id, input_per_million, output_per_million, currency)"
                      " VALUES (1, %s, %s, %s) ON CONFLICT (id) DO NOTHING", DEFAULT_RATES)

    def record(self, r: UsageRecord) -> None:
        self._execute("INSERT INTO token_usage (owner, kind, model, prompt_tokens, completion_tokens, total_tokens)"
                      " VALUES (%s, %s, %s, %s, %s, %s)",
                      (r.user, r.kind, r.model, r.prompt_tokens, r.completion_tokens, r.total_tokens))

    def remember_user(self, sub: str, username: str, name: str) -> None:
        """Keep a user's current username and display name, for the administrator's table."""
        self._execute("INSERT INTO usage_users (sub, username, name) VALUES (%s, %s, %s)"
                      " ON CONFLICT (sub) DO UPDATE SET username = EXCLUDED.username, name = EXCLUDED.name, seen_at = now()",
                      (sub, username, name))

    def rates(self) -> Rates:
        r = self._execute("SELECT input_per_million, output_per_million, currency, updated_at, updated_by"
                          " FROM usage_rates WHERE id = 1").fetchone()
        return Rates(input_per_million=r[0], output_per_million=r[1], currency=r[2], updated_at=r[3], updated_by=r[4])

    def set_rates(self, rates: Rates, by: str) -> Rates:
        self._execute("UPDATE usage_rates SET input_per_million = %s, output_per_million = %s, currency = %s,"
                      " updated_at = now(), updated_by = %s WHERE id = 1",
                      (rates.input_per_million, rates.output_per_million, rates.currency, by))
        return self.rates()

    def report(self, start: datetime, end: datetime, owner: str | None) -> UsageReport:
        """Usage between ``start`` and ``end``: ``owner``'s own, or everyone's with ``owner=None``."""
        step, label = step_for(end - start)
        mine = "AND owner = %(owner)s" if owner is not None else ""
        p = {"start": start, "end": end, "owner": owner, "step": step, "tz": self.tz, "origin": ORIGIN}
        totals = _totals(self._execute(
            f"SELECT count(*), sum(prompt_tokens), sum(completion_tokens) FROM token_usage"
            f" WHERE at >= %(start)s AND at < %(end)s {mine}", p).fetchone())
        series = [UsageBucket(start=r[0], **_totals(r[1:]).model_dump()) for r in self._execute(f"""
            WITH b AS (SELECT generate_series(date_bin(%(step)s, %(start)s AT TIME ZONE %(tz)s, %(origin)s),
                                              %(end)s AT TIME ZONE %(tz)s - interval '1 microsecond', %(step)s) AS local_start),
                 u AS (SELECT date_bin(%(step)s, at AT TIME ZONE %(tz)s, %(origin)s) AS local_start,
                              count(*) AS n, sum(prompt_tokens) AS p, sum(completion_tokens) AS c
                         FROM token_usage WHERE at >= %(start)s AND at < %(end)s {mine} GROUP BY 1)
            SELECT b.local_start AT TIME ZONE %(tz)s, u.n, u.p, u.c FROM b LEFT JOIN u USING (local_start)
             ORDER BY 1""", p).fetchall()]
        by_kind = {r[0]: _totals(r[1:]) for r in self._execute(
            f"SELECT kind, count(*), sum(prompt_tokens), sum(completion_tokens) FROM token_usage"
            f" WHERE at >= %(start)s AND at < %(end)s {mine} GROUP BY kind ORDER BY kind", p).fetchall()}
        return UsageReport(start=start, end=end, step=label, totals=totals, series=series, by_kind=by_kind)

    def admin_report(self, start: datetime, end: datetime) -> AdminUsageReport:
        """The office's usage: totals, per user (most tokens first) and the notional cost."""
        base = self.report(start, end, owner=None)
        rates = self.rates()
        per_user = []
        for r in self._execute(
                "SELECT t.owner, n.username, n.name, count(*), sum(t.prompt_tokens), sum(t.completion_tokens)"
                "  FROM token_usage t LEFT JOIN usage_users n ON n.sub = t.owner"
                " WHERE t.at >= %s AND t.at < %s GROUP BY 1, 2, 3"
                " ORDER BY sum(t.prompt_tokens) + sum(t.completion_tokens) DESC", (start, end)).fetchall():
            totals = _totals(r[3:])
            per_user.append(UserUsage(user_id=r[0], username=r[1], name=r[2], totals=totals,
                                      cost=cost(totals.prompt_tokens, totals.completion_tokens, rates)))
        return AdminUsageReport(**base.model_dump(), per_user=per_user, rates=rates,
                                cost=cost(base.totals.prompt_tokens, base.totals.completion_tokens, rates))


def parse_range(start: datetime | None, end: datetime | None, now: datetime | None = None) -> tuple[datetime, datetime]:
    """The requested range, defaulting to the last 24 hours. Raises ``ValueError`` if it makes no sense."""
    now = now or datetime.now(UTC)
    end = end or now
    start = start or end - timedelta(days=1)
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end need a time zone (e.g. 2026-10-10T00:00:00+02:00)")
    if start >= end:
        raise ValueError("start must be before end")
    if end - start > MAX_SPAN:
        raise ValueError("the range can be at most five years")
    return start, end
