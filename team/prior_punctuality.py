"""Prior-period comparison for the punctuality report.

Backend only — no views, templates, or UI. Read-only. Built ON
TOP of :func:`team.punctuality.punctuality_report` — figures for
both windows are that service's verbatim; never recomputed. For
an inclusive current window ``[start_date, end_date]`` of
``length`` days, the prior period is the equal-length window
immediately before it: ``[start_date - length, start_date - 1]``.
Each metric carries ``current``, ``prior``, ``delta``
(``current - prior``) and ``percent_change`` (``delta / prior *
100``, Decimal, two places, ROUND_HALF_UP), ``None`` when the
prior value is zero. ``average_late_minutes`` is a Decimal in
both windows (``0.00`` when no shift is late), so its delta is
always present and only its percent change can be ``None``.
``by_staff`` is the union of both windows' staff rows (a member
rostered in only one window gets zeros on the other side),
ordered by display name then id. A reversed window, a missing
salon, or a missing date raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from team.availability import _tz
from team.punctuality import StaffPunctuality, punctuality_report

__all__ = ["MetricDelta", "ComponentDelta", "PunctualityDelta",
           "StaffPriorPunctuality", "PriorPunctualityReport", "PriorPunctuality",
           "prior_punctuality_report", "prior_punctuality",
           "prior_period_punctuality", "compare_punctuality", "get_prior_punctuality"]
_CENT = Decimal("0.01")
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
PunctualityDelta = MetricDelta

def _pct_change(current, prior):
    if prior is None or Decimal(prior) == 0:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior) * 100
            ).quantize(_CENT, rounding=ROUND_HALF_UP)

def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior),
                       int(current) - int(prior), _pct_change(current, prior))

def _decimal_delta(name, current, prior):
    current, prior = Decimal(current), Decimal(prior)
    delta = (current - prior).quantize(_CENT, rounding=ROUND_HALF_UP)
    return MetricDelta(name, current, prior, delta, _pct_change(current, prior))

def _empty_staff(member):
    return StaffPunctuality(staff_member=member)

@dataclass(frozen=True)
class StaffPriorPunctuality:
    staff_member: object = None
    current: object = None
    prior: object = None
    shifts_considered: MetricDelta = None
    on_time_count: MetricDelta = None
    late_count: MetricDelta = None
    missed_count: MetricDelta = None
    total_late_minutes: MetricDelta = None
    average_late_minutes: MetricDelta = None

    @property
    def staff_member_id(self): return self.staff_member.pk if self.staff_member else None
    @property
    def staff_name(self): return self.staff_member.display_name if self.staff_member else ""
    display_name = staff_name

    def as_dict(self):
        return {"staff_member_id": self.staff_member_id, "staff_name": self.staff_name,
                "shifts_considered": self.shifts_considered.as_dict(),
                "on_time_count": self.on_time_count.as_dict(),
                "late_count": self.late_count.as_dict(),
                "missed_count": self.missed_count.as_dict(),
                "total_late_minutes": self.total_late_minutes.as_dict(),
                "average_late_minutes": self.average_late_minutes.as_dict()}

@dataclass(frozen=True)
class PriorPunctualityReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    shifts_considered: MetricDelta = None
    on_time_count: MetricDelta = None
    late_count: MetricDelta = None
    missed_count: MetricDelta = None
    total_late_minutes: MetricDelta = None
    average_late_minutes: MetricDelta = None
    by_staff: tuple = field(default_factory=tuple)

    salon_id = property(lambda self: getattr(self.salon, "pk", self.salon))
    per_staff = property(lambda self: self.by_staff)
    entries = per_staff
    staff = per_staff

    @property
    def previous(self): return self.prior
    @property
    def days(self): return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    @property
    def length(self): return self.days

    def for_staff(self, staff_member):
        key = getattr(staff_member, "pk", staff_member)
        return next((s for s in self.by_staff if s.staff_member_id == key), None)

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                "shifts_considered": self.shifts_considered.as_dict(),
                "on_time_count": self.on_time_count.as_dict(),
                "late_count": self.late_count.as_dict(),
                "missed_count": self.missed_count.as_dict(),
                "total_late_minutes": self.total_late_minutes.as_dict(),
                "average_late_minutes": self.average_late_minutes.as_dict(),
                "by_staff": [s.as_dict() for s in self.by_staff]}

    __iter__ = lambda self: iter(self.by_staff)  # noqa: E731
    __len__ = lambda self: len(self.by_staff)  # noqa: E731

PriorPunctuality = PriorPunctualityReport

_METRICS = ("shifts_considered", "on_time_count", "late_count", "missed_count",
            "total_late_minutes", "average_late_minutes")

def _deltas(current, prior):
    out = {}
    for name in _METRICS:
        cur, pri = getattr(current, name), getattr(prior, name)
        out[name] = (_decimal_delta(name, cur, pri) if name == "average_late_minutes"
                     else _count_delta(name, cur, pri))
    return out

def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))

def prior_punctuality_report(salon, date_from=None, date_to=None, *,
                             start_date=None, end_date=None, **kwargs):
    """Return the punctuality comparison for ``salon``.

    Call as ``(salon, first, last)``, ``(salon, day)`` for one day,
    or with ``start_date=`` / ``end_date=`` aliases (``start`` /
    ``end`` / ``since`` / ``until`` also accepted). Raises
    ``ValueError`` if the salon or a date is missing, or the
    window is reversed.
    """
    if salon is None:
        raise ValueError("prior punctuality comparison needs a salon")
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
    tz = _tz(salon)
    first, last = _as_date(date_from, tz), _as_date(date_to, tz)
    if last < first:
        raise ValueError("end_date must be on or after start_date.")
    length = (last - first).days + 1
    p_end, p_start = first - timedelta(days=1), first - timedelta(days=length)
    current = punctuality_report(salon, first, last)
    prior = punctuality_report(salon, p_start, p_end)
    cur = {e.staff_member_id: e for e in current.per_staff}
    pri = {e.staff_member_id: e for e in prior.per_staff}
    members = {}
    for src in (current.per_staff, prior.per_staff):
        for e in src:
            members[e.staff_member_id] = e.staff_member
    by_staff = tuple(
        StaffPriorPunctuality(
            staff_member=members[key],
            current=cur.get(key) or _empty_staff(members[key]),
            prior=pri.get(key) or _empty_staff(members[key]),
            **_deltas(cur.get(key) or _empty_staff(members[key]),
                      pri.get(key) or _empty_staff(members[key])))
        for key in sorted(members, key=lambda k: (members[k].display_name, k)))
    return PriorPunctualityReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=p_start,
        prior_end_date=p_end, current=current, prior=prior,
        by_staff=by_staff, **_deltas(current, prior))

prior_punctuality = prior_punctuality_report
prior_period_punctuality = prior_punctuality_report
compare_punctuality = prior_punctuality_report
get_prior_punctuality = prior_punctuality_report
