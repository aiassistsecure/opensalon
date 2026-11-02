"""Prior-period comparison for the new-client count.

Backend only — no views, templates, or UI. Read-only. Built ON
TOP of :mod:`clients.new_clients`' own services verbatim:
totals are ``new_client_count`` for both windows and per-day
counts are bucketed from ``new_clients`` rows' first-visit
dates — never recounted. For an inclusive current window of
``length`` days, the prior period is the equal-length window
immediately before it. Per-day figures pair each current day
with the day ``length`` days earlier. Each figure carries
``current``, ``prior``, ``delta`` and ``percent_change``
(Decimal, two places, ROUND_HALF_UP), ``None`` when prior is
zero. Count-shaped ONLY: no client rows/names. A reversed or
missing window raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from clients.new_clients import new_client_count, new_clients

__all__ = ["MetricDelta", "CountDelta", "DayDelta", "PriorNewClientsReport",
           "PriorNewClients", "prior_new_clients_report", "prior_new_clients",
           "prior_period_new_clients", "compare_new_clients",
           "get_prior_new_clients"]
_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class MetricDelta:
    """One count in both periods, with its change."""

    component: str
    current: int = 0
    prior: int = 0
    delta: int = 0
    percent_change: Decimal | None = None

    @property
    def name(self): return self.component
    @property
    def previous(self): return self.prior
    @property
    def change(self): return self.delta
    @property
    def pct_change(self): return self.percent_change

    def as_dict(self):
        return {"component": self.component, "current": self.current,
                "prior": self.prior, "delta": self.delta,
                "percent_change": self.percent_change}

CountDelta = MetricDelta


def _pct_change(current, prior):
    if not prior:
        return None
    return ((Decimal(int(current)) - Decimal(int(prior)))
            / Decimal(int(prior)) * 100).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _delta(name, current, prior):
    current, prior = int(current), int(prior)
    return MetricDelta(name, current, prior, current - prior,
                       _pct_change(current, prior))


@dataclass(frozen=True)
class DayDelta:
    """One current day paired with its prior-window counterpart."""

    current_date: date = None
    prior_date: date = None
    count: MetricDelta = None

    @property
    def date(self): return self.current_date
    @property
    def current(self): return self.count.current
    @property
    def prior(self): return self.count.prior
    @property
    def delta(self): return self.count.delta
    @property
    def percent_change(self): return self.count.percent_change

    def as_dict(self):
        return {"current_date": self.current_date.isoformat(),
                "prior_date": self.prior_date.isoformat(), **self.count.as_dict()}


@dataclass(frozen=True)
class PriorNewClientsReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: int = 0
    prior: int = 0
    total: MetricDelta = None
    by_day: dict = field(default_factory=dict)

    @property
    def previous(self): return self.prior
    @property
    def count(self): return self.total
    @property
    def new_client_count(self): return self.total
    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    length = days

    def __getitem__(self, day): return self.by_day.get(day)
    def day_for(self, day): return self.by_day.get(day)

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                "total": self.total.as_dict() if self.total else None,
                "by_day": {d.isoformat(): r.as_dict() for d, r in self.by_day.items()}}

PriorNewClients = PriorNewClientsReport


def _tz_for(salon):
    name = getattr(salon, "timezone", None) if salon is not None else None
    if name:
        try:
            return ZoneInfo(str(name))
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            pass
    return timezone.get_current_timezone()


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if timezone.is_aware(value) else value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            return _as_date(datetime.fromisoformat(value.strip()), tz)
    raise TypeError(f"expected a date or datetime, got {type(value).__name__}")


def _resolve(salon, start_date, end_date, kwargs):
    start, end = start_date, end_date
    for key in ("start", "period_start", "date_from", "since"):
        if start is None:
            start = kwargs.pop(key, None)
    for key in ("end", "period_end", "date_to", "until"):
        if end is None:
            end = kwargs.pop(key, None)
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(sorted(kwargs))}")
    if start is None or end is None:
        raise ValueError("Both start_date and end_date are required.")
    tz = _tz_for(salon)
    first, last = _as_date(start, tz), _as_date(end, tz)
    if last < first:
        raise ValueError("end_date must be on or after start_date.")
    return first, last


def _per_day(salon, first, last):
    counts = {}
    for row in new_clients(salon, first, last):
        day = row.first_appointment_date
        if day is not None:
            counts[day] = counts.get(day, 0) + 1
    return counts


def prior_new_clients_report(salon=None, start_date=None, end_date=None, **kwargs):
    """Return the new-client count comparison for the window.

    Arguments mirror :func:`clients.new_clients.new_clients`
    (``salon`` optional; ``start`` / ``period_start`` /
    ``date_from`` and ``end`` / ``period_end`` / ``date_to``
    aliases accepted). Totals come from ``new_client_count``
    verbatim for both windows; per-day counts bucket
    ``new_clients`` first-visit dates, zero-filled for every
    day of the current window, each paired with the day
    ``length`` days earlier.
    """
    first, last = _resolve(salon, start_date, end_date, kwargs)
    length = (last - first).days + 1
    prior_end = first - timedelta(days=1)
    prior_start = first - timedelta(days=length)
    current_total = new_client_count(salon, first, last)
    prior_total = new_client_count(salon, prior_start, prior_end)
    current_days, prior_days = _per_day(salon, first, last), _per_day(
        salon, prior_start, prior_end)
    by_day = {}
    for offset in range(length):
        day = first + timedelta(days=offset)
        counterpart = day - timedelta(days=length)
        by_day[day] = DayDelta(current_date=day, prior_date=counterpart,
                               count=_delta(day.isoformat(),
                                            current_days.get(day, 0),
                                            prior_days.get(counterpart, 0)))
    return PriorNewClientsReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=prior_start,
        prior_end_date=prior_end, current=current_total, prior=prior_total,
        total=_delta("total", current_total, prior_total), by_day=by_day)


prior_new_clients = prior_new_clients_report
prior_period_new_clients = prior_new_clients_report
compare_new_clients = prior_new_clients_report
get_prior_new_clients = prior_new_clients_report
