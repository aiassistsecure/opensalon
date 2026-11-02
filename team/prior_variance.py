"""Prior-period comparison for the rostered-vs-actual variance report.

Backend only, read-only, built ON TOP of
:func:`team.variance.roster_variance` — figures for both windows
are that service's verbatim. For an inclusive current window of
``length`` days, the prior period is the equal-length window
immediately before it. Each metric carries ``current``, ``prior``,
``delta`` and ``percent_change`` (Decimal, 2dp, ROUND_HALF_UP),
``None`` when prior is zero. ``by_staff`` is the union of both
windows' rows, ordered by display name then id. A reversed
window, missing salon, or missing date raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from team.availability import _tz
from team.variance import StaffVariance, roster_variance

__all__ = ["MetricDelta", "ComponentDelta", "VarianceDelta",
           "StaffPriorVariance", "PriorVarianceReport", "PriorVariance",
           "prior_variance_report", "prior_variance",
           "prior_period_variance", "compare_variance",
           "get_prior_variance", "prior_roster_variance"]
_CENT = Decimal("0.01")
_METRICS = ("rostered_minutes", "actual_minutes", "variance_minutes",
            "days_rostered", "days_attended", "absence_days")


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
VarianceDelta = MetricDelta

def _pct_change(current, prior):
    if prior is None or Decimal(prior) == 0:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior) * 100
            ).quantize(_CENT, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior),
                       int(current) - int(prior), _pct_change(current, prior))


def _empty_staff(member):
    return StaffVariance(staff_member=member)

@dataclass(frozen=True)
class StaffPriorVariance:
    staff_member: object = None
    current: object = None
    prior: object = None
    rostered_minutes: MetricDelta = None
    actual_minutes: MetricDelta = None
    variance_minutes: MetricDelta = None
    days_rostered: MetricDelta = None
    days_attended: MetricDelta = None
    absence_days: MetricDelta = None

    @property
    def staff_member_id(self): return self.staff_member.pk if self.staff_member else None
    @property
    def staff_name(self): return self.staff_member.display_name if self.staff_member else ""
    display_name = staff_name

    def as_dict(self):
        return {"staff_member_id": self.staff_member_id, "staff_name": self.staff_name,
                **{m: getattr(self, m).as_dict() for m in _METRICS}}


@dataclass(frozen=True)
class PriorVarianceReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    rostered_minutes: MetricDelta = None
    actual_minutes: MetricDelta = None
    variance_minutes: MetricDelta = None
    days_rostered: MetricDelta = None
    days_attended: MetricDelta = None
    absence_days: MetricDelta = None
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
                **{m: getattr(self, m).as_dict() for m in _METRICS},
                "by_staff": [s.as_dict() for s in self.by_staff]}

    __iter__ = lambda self: iter(self.by_staff)  # noqa: E731
    __len__ = lambda self: len(self.by_staff)  # noqa: E731


PriorVariance = PriorVarianceReport

def _deltas(current, prior):
    return {name: _count_delta(name, getattr(current, name), getattr(prior, name))
            for name in _METRICS}


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def prior_variance_report(salon, date_from=None, date_to=None, *,
                          start_date=None, end_date=None, **kwargs):
    """Return the variance comparison for ``salon``.

    Call as ``(salon, first, last)``, ``(salon, day)`` for one day,
    or with ``start_date=`` / ``end_date=`` aliases (``start`` /
    ``end`` / ``since`` / ``until`` also accepted). Raises
    ``ValueError`` if the salon or a date is missing, or the
    window is reversed.
    """
    if salon is None:
        raise ValueError("prior variance comparison needs a salon")
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
    current = roster_variance(salon, first, last)
    prior = roster_variance(salon, p_start, p_end)
    cur = {e.staff_member_id: e for e in current.per_staff}
    pri = {e.staff_member_id: e for e in prior.per_staff}
    members = {}
    for src in (current.per_staff, prior.per_staff):
        for e in src:
            members[e.staff_member_id] = e.staff_member
    by_staff = tuple(
        StaffPriorVariance(
            staff_member=members[key],
            current=cur.get(key) or _empty_staff(members[key]),
            prior=pri.get(key) or _empty_staff(members[key]),
            **_deltas(cur.get(key) or _empty_staff(members[key]),
                      pri.get(key) or _empty_staff(members[key])))
        for key in sorted(members, key=lambda k: (members[k].display_name, k)))
    return PriorVarianceReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=p_start,
        prior_end_date=p_end, current=current, prior=prior,
        by_staff=by_staff, **_deltas(current, prior))


prior_variance = prior_variance_report
prior_period_variance = prior_variance_report
compare_variance = prior_variance_report
get_prior_variance = prior_variance_report
prior_roster_variance = prior_variance_report
