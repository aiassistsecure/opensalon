"""Prior-period comparison for per-stylist utilization.

Backend only — no views, templates, or UI. Read-only. Built ON
TOP of :func:`bookings.utilization.staff_utilization` — figures
for both windows are that service's verbatim; never recomputed.
For an inclusive current window ``[start_date, end_date]`` of
``length`` days, the prior period is the equal-length window
immediately before it: ``[start_date - length, start_date - 1]``.
Count / minute metrics carry ``current``, ``prior``, ``delta``
(``current - prior``) and ``percent_change`` (``delta / prior *
100``, Decimal, two places, ROUND_HALF_UP), ``None`` when the
prior value is zero. ``utilization`` is the base service's float
fraction (``0.0`` when rostered is 0, never ``None``): its
``delta`` is ``current - prior`` as a float and its
``percent_change`` follows the same rule, ``None`` when the
prior utilization is zero. ``by_staff`` is the union of both
windows' staff rows (one-window staff get zeros on the other
side), ordered by display name then id. A reversed window
raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from bookings.availability import _tz
from bookings.utilization import StaffUtilization, staff_utilization

__all__ = ["MetricDelta", "ComponentDelta", "UtilizationDelta",
           "StaffPriorUtilization", "PriorUtilizationReport",
           "PriorUtilization", "prior_utilization_report",
           "prior_utilization", "prior_period_utilization",
           "compare_utilization", "get_prior_utilization"]
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
UtilizationDelta = MetricDelta


def _dec(value):
    return Decimal(str(value))


def _pct_change(current, prior):
    if prior is None or _dec(prior) == 0:
        return None
    return ((_dec(current) - _dec(prior)) / _dec(prior) * 100
            ).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior),
                       int(current) - int(prior), _pct_change(current, prior))


def _utilization_delta(name, current, prior):
    delta = float(_dec(current) - _dec(prior))
    return MetricDelta(name, float(current), float(prior), delta,
                       _pct_change(current, prior))


def _empty_staff(member):
    return StaffUtilization(staff_member=member, appointment_count=0,
                            booked_minutes=0, rostered_minutes=0)


@dataclass(frozen=True)
class StaffPriorUtilization:
    staff_member: object = None
    current: object = None
    prior: object = None
    appointment_count: MetricDelta = None
    booked_minutes: MetricDelta = None
    rostered_minutes: MetricDelta = None
    utilization: MetricDelta = None

    @property
    def staff_member_id(self): return self.staff_member.pk if self.staff_member else None
    @property
    def staff_name(self): return self.staff_member.display_name if self.staff_member else ""
    @property
    def display_name(self): return self.staff_name
    @property
    def current_utilization(self): return self.current.utilization if self.current else None
    @property
    def prior_utilization(self): return self.prior.utilization if self.prior else None

    def as_dict(self):
        return {"staff_member_id": self.staff_member_id, "staff_name": self.staff_name,
                "appointment_count": self.appointment_count.as_dict(),
                "booked_minutes": self.booked_minutes.as_dict(),
                "rostered_minutes": self.rostered_minutes.as_dict(),
                "utilization": self.utilization.as_dict()}


@dataclass(frozen=True)
class PriorUtilizationReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    appointment_count: MetricDelta = None
    booked_minutes: MetricDelta = None
    rostered_minutes: MetricDelta = None
    utilization: MetricDelta = None
    by_staff: tuple = field(default_factory=tuple)

    @property
    def previous(self): return self.prior
    @property
    def days(self): return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    @property
    def length(self): return self.days
    @property
    def current_utilization(self): return self.current.utilization if self.current else None
    @property
    def prior_utilization(self): return self.prior.utilization if self.prior else None

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                "appointment_count": self.appointment_count.as_dict(),
                "booked_minutes": self.booked_minutes.as_dict(),
                "rostered_minutes": self.rostered_minutes.as_dict(),
                "utilization": self.utilization.as_dict(),
                "by_staff": [s.as_dict() for s in self.by_staff]}


PriorUtilization = PriorUtilizationReport


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def prior_utilization_report(salon, date_from=None, date_to=None, *,
                             start_date=None, end_date=None, **kwargs):
    """Return the utilization comparison for ``salon``.

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
    current = staff_utilization(salon, first, last)
    prior = staff_utilization(salon, p_start, p_end)
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
        by_staff.append(StaffPriorUtilization(
            staff_member=members[key], current=c, prior=p,
            appointment_count=_count_delta("appointment_count",
                                           c.appointment_count, p.appointment_count),
            booked_minutes=_count_delta("booked_minutes",
                                        c.booked_minutes, p.booked_minutes),
            rostered_minutes=_count_delta("rostered_minutes",
                                          c.rostered_minutes, p.rostered_minutes),
            utilization=_utilization_delta("utilization",
                                           c.utilization, p.utilization)))
    return PriorUtilizationReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=p_start,
        prior_end_date=p_end, current=current, prior=prior,
        appointment_count=_count_delta("appointment_count",
                                       current.appointment_count, prior.appointment_count),
        booked_minutes=_count_delta("booked_minutes",
                                    current.booked_minutes, prior.booked_minutes),
        rostered_minutes=_count_delta("rostered_minutes",
                                      current.rostered_minutes, prior.rostered_minutes),
        utilization=_utilization_delta("utilization",
                                       current.utilization, prior.utilization),
        by_staff=tuple(by_staff))


prior_utilization = prior_utilization_report
prior_period_utilization = prior_utilization_report
compare_utilization = prior_utilization_report
get_prior_utilization = prior_utilization_report
