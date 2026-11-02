"""Prior-week comparison for the roster week report.

Backend only, read-only, built ON TOP of
:func:`team.roster_week.roster_week` — figures for both weeks are
that service's verbatim. The prior period is the preceding week
(the roster's natural prior): the seven days immediately before
the current week's Monday. Each metric (per-staff and salon
``total_minutes`` + ``working_days``) carries ``current``,
``prior``, ``delta`` and ``percent_change`` (Decimal, 2dp,
ROUND_HALF_UP), ``None`` when prior is zero. ``by_staff`` is the
union of both weeks' entries, ordered by display name then id,
with zeros on the missing side. An invalid week start or a
missing salon raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from team.availability import _tz
from team.roster_week import StaffWeekRoster, roster_week

__all__ = ["MetricDelta", "ComponentDelta", "RosterWeekDelta",
           "StaffPriorRosterWeek", "PriorRosterWeekReport",
           "PriorRosterWeek", "prior_roster_week_report",
           "prior_roster_week", "prior_period_roster_week",
           "compare_roster_week", "get_prior_roster_week"]
_CENT = Decimal("0.01")
_METRICS = ("total_minutes", "working_days")


@dataclass(frozen=True)
class MetricDelta:
    """One metric in both weeks, with its change."""

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
RosterWeekDelta = MetricDelta


def _pct_change(current, prior):
    if prior is None or Decimal(prior) == 0:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior) * 100
            ).quantize(_CENT, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior),
                       int(current) - int(prior), _pct_change(current, prior))


def _empty_staff(member):
    return StaffWeekRoster(
        staff_member=member,
        online_bookable=getattr(member, "online_bookable", True), days=())


def _staff_value(entry, name):
    return int(getattr(entry, name))


def _salon_value(week, name):
    if name == "total_minutes":
        return int(week.total_minutes)
    return int(sum(e.working_days for e in week.entries))


@dataclass(frozen=True)
class StaffPriorRosterWeek:
    staff_member: object = None
    current: object = None
    prior: object = None
    total_minutes: MetricDelta = None
    working_days: MetricDelta = None

    @property
    def staff_member_id(self): return self.staff_member.pk if self.staff_member else None
    @property
    def staff_name(self): return self.staff_member.display_name if self.staff_member else ""
    display_name = staff_name
    @property
    def online_bookable(self):
        src = self.current or self.prior
        return src.online_bookable if src is not None else None

    def as_dict(self):
        return {"staff_member_id": self.staff_member_id, "staff_name": self.staff_name,
                **{m: getattr(self, m).as_dict() for m in _METRICS}}


@dataclass(frozen=True)
class PriorRosterWeekReport:
    salon: object = None
    week_start: object = None
    week_end: object = None
    prior_week_start: object = None
    prior_week_end: object = None
    current: object = None
    prior: object = None
    total_minutes: MetricDelta = None
    working_days: MetricDelta = None
    by_staff: tuple = field(default_factory=tuple)

    salon_id = property(lambda self: getattr(self.salon, "pk", self.salon))
    per_staff = property(lambda self: self.by_staff)
    entries = per_staff
    staff = per_staff
    start_date = property(lambda self: self.week_start)
    end_date = property(lambda self: self.week_end)
    prior_start_date = property(lambda self: self.prior_week_start)
    prior_end_date = property(lambda self: self.prior_week_end)

    @property
    def previous(self): return self.prior

    def for_staff(self, staff_member):
        key = getattr(staff_member, "pk", staff_member)
        return next((s for s in self.by_staff if s.staff_member_id == key), None)

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"week_start": iso(self.week_start), "week_end": iso(self.week_end),
                "prior_week_start": iso(self.prior_week_start),
                "prior_week_end": iso(self.prior_week_end),
                **{m: getattr(self, m).as_dict() for m in _METRICS},
                "by_staff": [s.as_dict() for s in self.by_staff]}

    __iter__ = lambda self: iter(self.by_staff)  # noqa: E731
    __len__ = lambda self: len(self.by_staff)  # noqa: E731


PriorRosterWeek = PriorRosterWeekReport


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid week start {value!r}; expected YYYY-MM-DD.") from exc


def prior_roster_week_report(salon, week_start=None, **kwargs):
    """Return the roster-week comparison for ``salon``.

    ``week_start`` may be passed positionally or as ``week_start=``
    / ``start_date=`` / ``date=``; any date is snapped to its
    Monday by :func:`team.roster_week.roster_week`, exactly as
    that service defines it. Raises ``ValueError`` if the salon
    is missing or the week start is missing/invalid.
    """
    if week_start is None:
        week_start = (kwargs.pop("start_date", None) or kwargs.pop("date", None)
                      or kwargs.pop("start", None))
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    if salon is None:
        raise ValueError("prior roster week comparison needs a salon")
    if week_start is None:
        raise ValueError("prior roster week comparison needs a week start")
    parsed = _as_date(week_start, _tz(salon))
    current = roster_week(salon, parsed)
    monday = current.week_start
    prior_monday = monday - timedelta(days=7)
    prior = roster_week(salon, prior_monday)
    cur = {e.staff_member_id: e for e in current.entries}
    pri = {e.staff_member_id: e for e in prior.entries}
    members = {}
    for src in (current.entries, prior.entries):
        for e in src:
            members[e.staff_member_id] = e.staff_member

    def staff_deltas(key):
        c = cur.get(key) or _empty_staff(members[key])
        p = pri.get(key) or _empty_staff(members[key])
        return {m: _count_delta(m, _staff_value(c, m), _staff_value(p, m))
                for m in _METRICS}, c, p

    by_staff = []
    for key in sorted(members, key=lambda k: (members[k].display_name, k)):
        deltas, c, p = staff_deltas(key)
        by_staff.append(StaffPriorRosterWeek(
            staff_member=members[key], current=c, prior=p, **deltas))
    salon_deltas = {m: _count_delta(m, _salon_value(current, m),
                                    _salon_value(prior, m)) for m in _METRICS}
    return PriorRosterWeekReport(
        salon=salon, week_start=monday, week_end=current.week_end,
        prior_week_start=prior_monday, prior_week_end=prior.week_end,
        current=current, prior=prior, by_staff=tuple(by_staff), **salon_deltas)


prior_roster_week = prior_roster_week_report
prior_period_roster_week = prior_roster_week_report
compare_roster_week = prior_roster_week_report
get_prior_roster_week = prior_roster_week_report
