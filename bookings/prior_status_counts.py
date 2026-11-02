"""Prior-period comparison for appointment status counts.

Backend only — no views, templates, or UI. Read-only. Built ON
TOP of :func:`bookings.status_counts.appointment_status_counts`
— figures for both windows are that service's verbatim; never
recounted. For an inclusive current window ``[start_date,
end_date]`` of ``length`` days, the prior period is the
equal-length window immediately before it:
``[start_date - length, start_date - 1]``. The base service has
no per-staff breakdown, so none is invented here: salon totals
plus one metric per status in ``by_status``. Each metric carries
``current``, ``prior``, ``delta`` (``current - prior``) and
``percent_change`` (``delta / prior * 100``, Decimal, two
places, ROUND_HALF_UP), ``None`` when the prior value is zero.
A reversed window raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from bookings.availability import _tz
from bookings.status_counts import appointment_status_counts

__all__ = ["MetricDelta", "ComponentDelta", "StatusDelta",
           "PriorStatusCountsReport", "PriorStatusCounts",
           "prior_status_counts_report", "prior_status_counts",
           "prior_period_status_counts", "compare_status_counts",
           "get_prior_status_counts"]
_CENTS = Decimal("0.01")


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
StatusDelta = MetricDelta


def _pct_change(current, prior):
    if prior is None or Decimal(int(prior)) == 0:
        return None
    return ((Decimal(int(current)) - Decimal(int(prior)))
            / Decimal(int(prior)) * 100
            ).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior),
                       int(current) - int(prior), _pct_change(current, prior))


@dataclass(frozen=True)
class PriorStatusCountsReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    total: MetricDelta = None
    by_status: dict = field(default_factory=dict)

    @property
    def previous(self): return self.prior
    @property
    def days(self): return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    @property
    def length(self): return self.days
    @property
    def counts(self): return self.by_status

    def __getitem__(self, status):
        return self.by_status.get(str(status))

    def count_for(self, status):
        return self.by_status.get(str(status))

    # One MetricDelta attribute per known status.
    @property
    def booked(self): return self.by_status.get("booked")
    @property
    def confirmed(self): return self.by_status.get("confirmed")
    @property
    def arrived(self): return self.by_status.get("arrived")
    @property
    def in_service(self): return self.by_status.get("in_service")
    @property
    def completed(self): return self.by_status.get("completed")
    @property
    def cancelled(self): return self.by_status.get("cancelled")
    @property
    def no_show(self): return self.by_status.get("no_show")

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                "total": self.total.as_dict() if self.total else None,
                "by_status": {k: v.as_dict() for k, v in self.by_status.items()}}


PriorStatusCounts = PriorStatusCountsReport


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def prior_status_counts_report(salon, date_from=None, date_to=None, *,
                               start_date=None, end_date=None, **kwargs):
    """Return the status-counts comparison for ``salon``.

    Call as ``(salon, first, last)``, ``(salon, day)`` for one
    day, or with ``start_date=`` / ``end_date=`` aliases
    (``start`` / ``end`` / ``since`` / ``until`` also accepted).
    Raises ``ValueError`` if no date is given or reversed.
    """
    if date_from is None:
        date_from = start_date or kwargs.pop("start", kwargs.pop("since", None))
    if date_to is None:
        date_to = end_date or kwargs.pop("end", kwargs.pop("until", None))
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
    current = appointment_status_counts(salon, first, last)
    prior = appointment_status_counts(salon, p_start, p_end)
    statuses = list(current.by_status)
    statuses += [s for s in prior.by_status if s not in current.by_status]
    by_status = {s: _count_delta(s, current.by_status.get(s, 0),
                                 prior.by_status.get(s, 0)) for s in statuses}
    return PriorStatusCountsReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=p_start,
        prior_end_date=p_end, current=current, prior=prior,
        total=_count_delta("total", current.total, prior.total),
        by_status=by_status)


prior_status_counts = prior_status_counts_report
prior_period_status_counts = prior_status_counts_report
compare_status_counts = prior_status_counts_report
get_prior_status_counts = prior_status_counts_report
