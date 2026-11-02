"""Prior-period comparison for paid/unpaid break totals.

Backend only, read-only. Built ON TOP of
:func:`bookings.break_totals.break_totals` — figures verbatim,
never recounted. Prior period is the equal-length window
immediately before ``[start_date, end_date]``. Each metric
carries current/prior/delta/percent_change (Decimal, 2 places,
ROUND_HALF_UP; ``None`` when prior is zero). ``by_staff`` is
the union of both windows, name order; ``staff_member`` scopes
both windows. A reversed window raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from bookings.availability import _tz
from bookings.break_totals import StaffBreakTotals, break_totals

__all__ = ["MetricDelta", "ComponentDelta", "BreakDelta", "StaffPriorBreakTotals",
           "PriorBreakTotalsReport", "PriorBreakTotals", "prior_break_totals_report",
           "prior_break_totals", "prior_period_break_totals", "compare_break_totals",
           "get_prior_break_totals"]
_CENTS = Decimal("0.01")
METRICS = ("break_count", "total_break_minutes", "paid_break_count",
           "paid_minutes", "unpaid_break_count", "unpaid_minutes")


@dataclass(frozen=True)
class MetricDelta:
    """One metric in both periods, with its change."""

    component: str
    current: object = None
    prior: object = None
    delta: object = None
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


ComponentDelta = MetricDelta
BreakDelta = MetricDelta


def _pct_change(current, prior):
    if prior is None or Decimal(int(prior)) == 0:
        return None
    return ((Decimal(int(current)) - Decimal(int(prior))) / Decimal(int(prior)) * 100
            ).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior), int(current) - int(prior),
                       _pct_change(current, prior))


def _empty_staff(staff_id, staff_name):
    return StaffBreakTotals(staff_member_id=staff_id, staff_name=staff_name)


@dataclass(frozen=True)
class StaffPriorBreakTotals:
    staff_member_id: int = None
    staff_name: str = ""
    current: object = None
    prior: object = None
    break_count: MetricDelta = None
    total_break_minutes: MetricDelta = None
    paid_break_count: MetricDelta = None
    paid_minutes: MetricDelta = None
    unpaid_break_count: MetricDelta = None
    unpaid_minutes: MetricDelta = None

    @property
    def display_name(self): return self.staff_name

    def as_dict(self):
        return {"staff_member_id": self.staff_member_id,
                "staff_name": self.staff_name,
                **{m: getattr(self, m).as_dict() for m in METRICS}}


@dataclass(frozen=True)
class PriorBreakTotalsReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    break_count: MetricDelta = None
    total_break_minutes: MetricDelta = None
    paid_break_count: MetricDelta = None
    paid_minutes: MetricDelta = None
    unpaid_break_count: MetricDelta = None
    unpaid_minutes: MetricDelta = None
    by_staff: tuple = field(default_factory=tuple)

    @property
    def previous(self): return self.prior
    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    @property
    def length(self): return self.days

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date), "prior_end_date": iso(self.prior_end_date),
                **{m: getattr(self, m).as_dict() for m in METRICS}, "by_staff": [s.as_dict() for s in self.by_staff]}


PriorBreakTotals = PriorBreakTotalsReport


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def prior_break_totals_report(salon, date_from=None, date_to=None, *,
                              staff_member=None, start_date=None,
                              end_date=None, **kwargs):
    """Return the break-totals comparison for ``salon``.

    Call as ``(salon, first, last)``, ``(salon, day)``, or with
    ``start_date=``/``end_date=`` aliases (``start``/``end``/
    ``since``/``until``). Raises ``ValueError`` if missing/reversed.
    """
    if date_from is None:
        date_from = start_date or kwargs.pop("start", kwargs.pop("since", None))
    if date_to is None:
        date_to = end_date or kwargs.pop("end", kwargs.pop("until", None))
    if "staff_member" in kwargs:
        staff_member = kwargs.pop("staff_member")
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    if date_from is None:
        raise ValueError("Both start_date and end_date are required.")
    if date_to is None:
        date_to = date_from
    if salon is not None:
        tz = _tz(salon)
    else:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("UTC")
    first, last = _as_date(date_from, tz), _as_date(date_to, tz)
    if last < first:
        raise ValueError("end_date must be on or after start_date.")
    length = (last - first).days + 1
    p_end, p_start = first - timedelta(days=1), first - timedelta(days=length)
    current = break_totals(salon, first, last, staff_member=staff_member)
    prior = break_totals(salon, p_start, p_end, staff_member=staff_member)
    cur = {s.staff_member_id: s for s in current.by_staff}
    pri = {s.staff_member_id: s for s in prior.by_staff}
    names = {}
    for src in (current.by_staff, prior.by_staff):
        for s in src:
            names[s.staff_member_id] = s.staff_name
    by_staff = []
    for key in sorted(names, key=lambda k: (names[k], k)):
        c = cur.get(key) or _empty_staff(key, names[key])
        p = pri.get(key) or _empty_staff(key, names[key])
        by_staff.append(StaffPriorBreakTotals(
            staff_member_id=key, staff_name=names[key], current=c, prior=p,
            **{m: _count_delta(m, getattr(c, m), getattr(p, m)) for m in METRICS}))
    return PriorBreakTotalsReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=p_start,
        prior_end_date=p_end, current=current, prior=prior,
        **{m: _count_delta(m, getattr(current, m), getattr(prior, m))
           for m in METRICS},
        by_staff=tuple(by_staff))


prior_break_totals = prior_break_totals_report
prior_period_break_totals = prior_break_totals_report
compare_break_totals = prior_break_totals_report
get_prior_break_totals = prior_break_totals_report
