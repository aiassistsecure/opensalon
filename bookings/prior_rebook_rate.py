"""Prior-period comparison for the rebook rate.

Backend only — no views, templates, or UI. Read-only. Built ON
TOP of :func:`bookings.rebook_rate.rebook_rate_report` — figures
for both windows are that service's verbatim; never recounted.
For an inclusive current window ``[start_date, end_date]`` of
``length`` days, the prior period is the equal-length window
immediately before it: ``[start_date - length, start_date - 1]``.
Each metric carries ``current``, ``prior``, ``delta``
(``current - prior``) and ``percent_change`` (``delta / prior *
100``, Decimal, two places, ROUND_HALF_UP), ``None`` when the
prior value is zero. A rate is ``None`` when its window's
``completed`` is zero; a rate delta / percent change is ``None``
when either rate is ``None`` or the prior rate is zero.
``by_staff`` is the union of both windows' staff rows (one-window
staff get zeros / ``None`` rate on the other side), ordered by
display name then id. A reversed window raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from bookings.availability import _tz
from bookings.rebook_rate import StaffRebookRate, rebook_rate_report

__all__ = ["MetricDelta", "ComponentDelta", "RebookDelta",
           "StaffPriorRebookRate", "PriorRebookRateReport",
           "PriorRebookRate", "prior_rebook_rate_report",
           "prior_rebook_rate", "prior_period_rebook_rate",
           "compare_rebook_rate", "get_prior_rebook_rate"]
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
RebookDelta = MetricDelta


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


def _empty_staff(member):
    return StaffRebookRate(staff_member=member, completed=0, rebooked=0,
                           rebook_rate_percent=None)


@dataclass(frozen=True)
class StaffPriorRebookRate:
    staff_member: object = None
    current: object = None
    prior: object = None
    completed: MetricDelta = None
    rebooked: MetricDelta = None
    rebook_rate_percent: MetricDelta = None

    @property
    def staff_member_id(self): return self.staff_member.pk if self.staff_member else None
    @property
    def staff_name(self): return self.staff_member.display_name if self.staff_member else ""
    @property
    def display_name(self): return self.staff_name
    @property
    def rate(self): return self.rebook_rate_percent
    @property
    def current_rate(self): return self.current.rebook_rate_percent if self.current else None
    @property
    def prior_rate(self): return self.prior.rebook_rate_percent if self.prior else None

    def as_dict(self):
        return {"staff_member_id": self.staff_member_id, "staff_name": self.staff_name,
                "completed": self.completed.as_dict(), "rebooked": self.rebooked.as_dict(),
                "rebook_rate_percent": self.rebook_rate_percent.as_dict()}


@dataclass(frozen=True)
class PriorRebookRateReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    total_appointments: MetricDelta = None
    completed: MetricDelta = None
    rebooked: MetricDelta = None
    rebook_rate_percent: MetricDelta = None
    by_staff: tuple = field(default_factory=tuple)

    @property
    def previous(self): return self.prior
    @property
    def days(self): return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    @property
    def length(self): return self.days
    @property
    def rate(self): return self.rebook_rate_percent
    @property
    def current_rate(self): return self.current.rebook_rate_percent if self.current else None
    @property
    def prior_rate(self): return self.prior.rebook_rate_percent if self.prior else None

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                "total_appointments": self.total_appointments.as_dict(),
                "completed": self.completed.as_dict(), "rebooked": self.rebooked.as_dict(),
                "rebook_rate_percent": self.rebook_rate_percent.as_dict(),
                "by_staff": [s.as_dict() for s in self.by_staff]}


PriorRebookRate = PriorRebookRateReport


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def prior_rebook_rate_report(salon, date_from=None, date_to=None, *,
                             start_date=None, end_date=None, **kwargs):
    """Return the rebook-rate comparison for ``salon``.

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
    current = rebook_rate_report(salon, first, last)
    prior = rebook_rate_report(salon, p_start, p_end)
    cur = {s.staff_member_id: s for s in current.by_staff}
    pri = {s.staff_member_id: s for s in prior.by_staff}
    members = {}
    for src in (current.by_staff, prior.by_staff):
        for s in src:
            members[s.staff_member_id] = s.staff_member
    by_staff = []
    for key in sorted(members, key=lambda k: (members[k].display_name, k)):
        c = cur.get(key) or _empty_staff(members[key])
        p = pri.get(key) or _empty_staff(members[key])
        by_staff.append(StaffPriorRebookRate(
            staff_member=members[key], current=c, prior=p,
            completed=_count_delta("completed", c.completed, p.completed),
            rebooked=_count_delta("rebooked", c.rebooked, p.rebooked),
            rebook_rate_percent=_rate_delta("rebook_rate_percent",
                                            c.rebook_rate_percent, p.rebook_rate_percent)))
    return PriorRebookRateReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=p_start,
        prior_end_date=p_end, current=current, prior=prior,
        total_appointments=_count_delta("total_appointments",
                                        current.total_appointments, prior.total_appointments),
        completed=_count_delta("completed", current.completed, prior.completed),
        rebooked=_count_delta("rebooked", current.rebooked, prior.rebooked),
        rebook_rate_percent=_rate_delta("rebook_rate_percent",
                                        current.rebook_rate_percent, prior.rebook_rate_percent),
        by_staff=tuple(by_staff))


prior_rebook_rate = prior_rebook_rate_report
prior_period_rebook_rate = prior_rebook_rate_report
compare_rebook_rate = prior_rebook_rate_report
get_prior_rebook_rate = prior_rebook_rate_report
