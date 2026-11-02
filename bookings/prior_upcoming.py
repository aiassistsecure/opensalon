"""Prior for upcoming counts (elapsed-window comparison).

Backend only, read-only. Built ON TOP of
:func:`bookings.upcoming.upcoming_appointments` — the wrapper
counts nothing itself beyond calling that service for both
windows; figures are its verbatim totals / per-day / per-staff
counts. Current window is the forward ``[start, start+days)``;
the prior window is the same service over the immediately
preceding equal-length ELAPSED window ``[start-days, start)``
— "booked ahead for the next N days vs appointments held in
the last N days". No as-of reconstruction is claimed: both
sides count stored rows in their window (cancelled excluded,
per the source). Each count carries current / prior / delta
and ``percent_change`` (Decimal, two places, ROUND_HALF_UP),
``None`` when prior is zero. ``by_day`` pairs days by offset;
``by_staff`` is the union of both windows, name order. A
missing salon or non-positive / unparseable window raises
``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from bookings.availability import _tz
from bookings.upcoming import DEFAULT_DAYS, upcoming_appointments

__all__ = ["MetricDelta", "ComponentDelta", "CountDelta",
           "DayPriorUpcoming", "StaffPriorUpcoming",
           "PriorUpcomingReport", "PriorUpcoming",
           "prior_upcoming_report", "prior_upcoming",
           "compare_upcoming", "get_prior_upcoming"]
_CENTS = Decimal("0.01")

@dataclass(frozen=True)
class MetricDelta:
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
    def elapsed(self): return self.prior
    @property
    def change(self): return self.delta
    @property
    def pct_change(self): return self.percent_change

    def as_dict(self):
        return {"component": self.component, "current": self.current,
                "prior": self.prior, "elapsed": self.prior,
                "delta": self.delta,
                "percent_change": self.percent_change}

ComponentDelta = MetricDelta
CountDelta = MetricDelta

def _pct_change(current, prior):
    if prior is None or Decimal(int(prior)) == 0:
        return None
    return ((Decimal(int(current)) - Decimal(int(prior)))
            / Decimal(int(prior)) * 100
            ).quantize(_CENTS, rounding=ROUND_HALF_UP)

def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior),
                       int(current) - int(prior),
                       _pct_change(current, prior))

@dataclass(frozen=True)
class DayPriorUpcoming:
    date: object = None
    elapsed_date: object = None
    count: MetricDelta = None

    @property
    def prior_date(self): return self.elapsed_date

    def as_dict(self):
        return {"date": self.date.isoformat() if self.date else None,
                "elapsed_date": (self.elapsed_date.isoformat()
                                 if self.elapsed_date else None),
                "prior_date": (self.elapsed_date.isoformat()
                               if self.elapsed_date else None),
                "count": self.count.as_dict() if self.count else None}

@dataclass(frozen=True)
class StaffPriorUpcoming:
    staff_member_id: int = None
    staff_name: str = ""
    staff_member: object = None
    count: MetricDelta = None

    @property
    def display_name(self): return self.staff_name

    def as_dict(self):
        return {"staff_member_id": self.staff_member_id,
                "staff_name": self.staff_name,
                "count": self.count.as_dict() if self.count else None}

@dataclass(frozen=True)
class PriorUpcomingReport:
    salon: object = None
    start: object = None
    end: object = None
    days: int = DEFAULT_DAYS
    elapsed_start: object = None
    elapsed_end: object = None
    current: object = None
    prior: object = None
    total: MetricDelta = None
    by_day: tuple = field(default_factory=tuple)
    by_staff: tuple = field(default_factory=tuple)

    @property
    def previous(self): return self.prior
    @property
    def elapsed(self): return self.prior
    @property
    def prior_start(self): return self.elapsed_start
    @property
    def prior_end(self): return self.elapsed_end
    @property
    def count(self): return self.total

    def as_dict(self):
        iso = lambda v: v.isoformat() if v else None  # noqa: E731
        return {"start": iso(self.start), "end": iso(self.end),
                "elapsed_start": iso(self.elapsed_start),
                "elapsed_end": iso(self.elapsed_end),
                "prior_start": iso(self.elapsed_start),
                "prior_end": iso(self.elapsed_end),
                "days": self.days,
                "total": self.total.as_dict() if self.total else None,
                "by_day": [d.as_dict() for d in self.by_day],
                "by_staff": [s.as_dict() for s in self.by_staff]}

PriorUpcoming = PriorUpcomingReport

def prior_upcoming_report(salon, start=None, days=DEFAULT_DAYS, **kwargs):
    """Return the upcoming-vs-elapsed comparison for ``salon``.

    ``start`` / ``days`` mean exactly what they mean in
    :func:`bookings.upcoming.upcoming_appointments`
    (``horizon_days`` / ``start_datetime`` / ``now`` aliases are
    honoured). Raises ``ValueError`` if the salon is missing or
    the window is not a positive whole number of days.
    """
    if "horizon_days" in kwargs:
        days = kwargs.pop("horizon_days")
    if start is None:
        start = kwargs.pop("start_datetime", kwargs.pop("now", None))
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    if salon is None:
        raise ValueError("A salon is required.")
    try:
        days = int(days)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid days {days!r}.") from exc
    if days <= 0:
        raise ValueError("days must be a positive whole number.")
    current = upcoming_appointments(salon, start, days)
    elapsed_start = current.start - timedelta(days=current.days)
    prior = upcoming_appointments(salon, elapsed_start, current.days)
    tz = _tz(salon)
    first_day = current.start.astimezone(tz).date()
    cur_days, ela_days = current.counts_by_day, prior.counts_by_day
    by_day = tuple(
        DayPriorUpcoming(
            date=first_day + timedelta(days=i),
            elapsed_date=first_day - timedelta(days=current.days - i),
            count=_count_delta(
                "count",
                cur_days.get(first_day + timedelta(days=i), 0),
                ela_days.get(first_day - timedelta(days=current.days - i), 0)))
        for i in range(current.days))
    members = {}
    for src in (current.by_staff, prior.by_staff):
        for entry in src:
            members[entry.staff_member_id] = entry.staff_member
    cur_staff, ela_staff = current.counts_by_staff, prior.counts_by_staff
    by_staff = tuple(
        StaffPriorUpcoming(
            staff_member_id=k, staff_name=members[k].display_name,
            staff_member=members[k],
            count=_count_delta("count", cur_staff.get(k, 0),
                               ela_staff.get(k, 0)))
        for k in sorted(members, key=lambda k: (members[k].display_name, k)))
    return PriorUpcomingReport(
        salon=salon, start=current.start, end=current.end,
        days=current.days, elapsed_start=prior.start,
        elapsed_end=prior.end, current=current, prior=prior,
        total=_count_delta("total", current.total, prior.total),
        by_day=by_day, by_staff=by_staff)

prior_upcoming = prior_upcoming_report
compare_upcoming = prior_upcoming_report
get_prior_upcoming = prior_upcoming_report
