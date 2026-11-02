"""Prior-period comparison for online cancellations.

Backend only, read-only. Built on top of
:mod:`onlinebooking.cancellations` — both windows' figures are
that service's verbatim, never recounted. For an inclusive
current window ``[start, end]`` of ``length`` days, the prior
period is ``[start - length, start - 1 day]``. Each count
carries ``current``, ``prior``, ``delta`` and
``percent_change`` (Decimal, two places, ROUND_HALF_UP),
``None`` when the prior count is zero. Missing salon or
bound, or a reversed window, raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from bookings.availability import _tz

from .cancellations import online_cancellation_summary

__all__ = ["CountDelta", "MetricDelta", "BreakdownDelta",
           "PriorCancellations", "PriorCancellationsComparison",
           "prior_cancellations", "prior_period_cancellations",
           "compare_cancellations", "get_prior_cancellations"]
_CENTS = Decimal("0.01")


def _pct(current, prior):
    if not prior:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior)
            * 100).quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CountDelta:
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


MetricDelta = CountDelta


@dataclass(frozen=True)
class BreakdownDelta:
    """One staff or service row compared across both windows."""
    section: str
    staff_member_id: int = None
    staff_name: str = ""
    service_id: int = None
    service_name: str = ""
    current: int = 0
    prior: int = 0

    @property
    def delta(self): return self.current - self.prior
    @property
    def percent_change(self): return _pct(self.current, self.prior)
    @property
    def name(self):
        return self.staff_name if self.section == "staff" else self.service_name


@dataclass(frozen=True)
class PriorCancellationsComparison:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    total: CountDelta = None
    by_staff: tuple = field(default_factory=tuple)
    by_service: tuple = field(default_factory=tuple)

    @property
    def salon_id(self): return getattr(self.salon, "pk", self.salon)
    @property
    def previous(self): return self.prior
    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    @property
    def deltas(self): return {"total": self.total}


PriorCancellations = PriorCancellationsComparison


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _breakdown(section, current_rows, prior_rows, key, make):
    cur = {key(r): r for r in current_rows}
    pri = {key(r): r for r in prior_rows}
    rows = [make(k, cur.get(k), pri.get(k)) for k in cur.keys() | pri.keys()]
    return tuple(sorted(rows, key=lambda r: (
        -r.current, -r.prior, r.name, r.staff_member_id or r.service_id or 0)))


def prior_cancellations(salon, date_from=None, date_to=None, *,
                        start_date=None, end_date=None, **kwargs):
    """Return the online-cancellations comparison for ``salon``."""
    if salon is None:
        raise ValueError("prior_cancellations needs a salon")
    if date_from is None:
        date_from = start_date or kwargs.pop(
            "start", kwargs.pop("since", kwargs.pop("day", None)))
    if date_to is None:
        date_to = end_date or kwargs.pop(
            "end", kwargs.pop("until", kwargs.pop("end_day", None)))
    if kwargs:
        raise TypeError(f"unexpected arguments: {', '.join(sorted(kwargs))}")
    if date_from is None or date_to is None:
        raise ValueError("prior_cancellations needs both a start and end")
    tz = _tz(salon)
    first, last = _as_date(date_from, tz), _as_date(date_to, tz)
    if last < first:
        raise ValueError("range end must not be before its start")
    length = (last - first).days + 1
    p_end, p_start = first - timedelta(days=1), first - timedelta(days=length)
    current = online_cancellation_summary(salon, first, last)
    prior = online_cancellation_summary(salon, p_start, p_end)
    total = CountDelta("total", current.total, prior.total,
                       current.total - prior.total,
                       _pct(current.total, prior.total))
    by_staff = _breakdown(
        "staff", current.by_staff, prior.by_staff,
        lambda r: r.staff_member_id,
        lambda k, c, p: BreakdownDelta(
            "staff", staff_member_id=k,
            staff_name=(c or p).staff_display_name,
            current=c.count if c else 0, prior=p.count if p else 0))
    by_service = _breakdown(
        "service", current.by_service, prior.by_service,
        lambda r: (r.service_id, r.service_name),
        lambda k, c, p: BreakdownDelta(
            "service", service_id=k[0], service_name=k[1],
            current=c.count if c else 0, prior=p.count if p else 0))
    return PriorCancellationsComparison(
        salon=salon, start_date=first, end_date=last,
        prior_start_date=p_start, prior_end_date=p_end,
        current=current, prior=prior, total=total,
        by_staff=by_staff, by_service=by_service)


prior_period_cancellations = prior_cancellations
compare_cancellations = prior_cancellations
get_prior_cancellations = prior_cancellations
