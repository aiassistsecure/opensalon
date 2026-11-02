"""Prior-period comparison for the no-show / late-cancel rate.

Backend only — no views, templates, or UI. Read-only. Built ON
TOP of :func:`bookings.noshow_rate.noshow_rate_report` — figures
for both windows are that service's verbatim; never recounted.
For an inclusive current window ``[start_date, end_date]`` of
``length`` days, the prior period is the equal-length window
immediately before it: ``[start_date - length, start_date - 1]``.
Each metric carries ``current``, ``prior``, ``delta``
(``current - prior``) and ``percent_change`` (``delta / prior *
100``, Decimal, two places, ROUND_HALF_UP), ``None`` when the
prior value is zero. A rate is ``None`` when its window's total
is zero; a rate delta / percent change is ``None`` when either
rate is ``None`` or the prior rate is zero. A reversed window
raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from bookings.availability import _tz
from bookings.noshow_rate import noshow_rate_report

__all__ = ["MetricDelta", "ComponentDelta", "NoShowDelta",
           "PriorNoShowRateReport", "PriorNoShowRate",
           "prior_noshow_rate_report", "prior_noshow_rate",
           "prior_period_noshow_rate", "compare_noshow_rate",
           "get_prior_noshow_rate"]
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
NoShowDelta = MetricDelta


def _pct_change(current, prior):
    if prior is None or Decimal(prior) == 0:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior) * 100
            ).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior),
                       int(current) - int(prior), _pct_change(current, prior))


def _rate_delta(name, current, prior):
    if current is None or prior is None:
        return MetricDelta(name, current, prior, None, None)
    delta = (Decimal(current) - Decimal(prior)).quantize(_CENTS, rounding=ROUND_HALF_UP)
    return MetricDelta(name, current, prior, delta, _pct_change(current, prior))


@dataclass(frozen=True)
class PriorNoShowRateReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    total_appointments: MetricDelta = None
    completed: MetricDelta = None
    no_shows: MetricDelta = None
    cancelled: MetricDelta = None
    late_cancellations: MetricDelta = None
    no_show_rate_percent: MetricDelta = None
    late_cancel_rate_percent: MetricDelta = None

    @property
    def previous(self): return self.prior
    @property
    def days(self): return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    @property
    def length(self): return self.days
    @property
    def no_show_rate(self): return self.no_show_rate_percent
    @property
    def late_cancel_rate(self): return self.late_cancel_rate_percent
    @property
    def current_no_show_rate(self): return self.current.no_show_rate_percent if self.current else None
    @property
    def prior_no_show_rate(self): return self.prior.no_show_rate_percent if self.prior else None
    @property
    def current_late_cancel_rate(self): return self.current.late_cancel_rate_percent if self.current else None
    @property
    def prior_late_cancel_rate(self): return self.prior.late_cancel_rate_percent if self.prior else None

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                "total_appointments": self.total_appointments.as_dict(),
                "completed": self.completed.as_dict(),
                "no_shows": self.no_shows.as_dict(),
                "cancelled": self.cancelled.as_dict(),
                "late_cancellations": self.late_cancellations.as_dict(),
                "no_show_rate_percent": self.no_show_rate_percent.as_dict(),
                "late_cancel_rate_percent": self.late_cancel_rate_percent.as_dict()}


PriorNoShowRate = PriorNoShowRateReport


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def prior_noshow_rate_report(salon, date_from=None, date_to=None, *,
                             start_date=None, end_date=None, **kwargs):
    """Return the no-show / late-cancel comparison for ``salon``.

    Call as ``(salon, first, last)``, ``(salon, day)`` for one day,
    or with ``start_date=`` / ``end_date=`` aliases (``start`` /
    ``end`` / ``since`` / ``until`` also accepted). Raises
    ``ValueError`` if no date is given or the window is reversed.
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
    current = noshow_rate_report(salon, first, last)
    prior = noshow_rate_report(salon, p_start, p_end)
    return PriorNoShowRateReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=p_start,
        prior_end_date=p_end, current=current, prior=prior,
        total_appointments=_count_delta("total_appointments",
                                        current.total_appointments, prior.total_appointments),
        completed=_count_delta("completed", current.completed, prior.completed),
        no_shows=_count_delta("no_shows", current.no_shows, prior.no_shows),
        cancelled=_count_delta("cancelled", current.cancelled, prior.cancelled),
        late_cancellations=_count_delta("late_cancellations",
                                        current.late_cancellations, prior.late_cancellations),
        no_show_rate_percent=_rate_delta("no_show_rate_percent",
                                         current.no_show_rate_percent, prior.no_show_rate_percent),
        late_cancel_rate_percent=_rate_delta("late_cancel_rate_percent",
                                             current.late_cancel_rate_percent,
                                             prior.late_cancel_rate_percent))


prior_noshow_rate = prior_noshow_rate_report
prior_period_noshow_rate = prior_noshow_rate_report
compare_noshow_rate = prior_noshow_rate_report
get_prior_noshow_rate = prior_noshow_rate_report
