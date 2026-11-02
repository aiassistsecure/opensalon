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
with zeros on the missing side. ``by_weekday`` carries the
salon totals per weekday too: for each of Monday–Sunday, the
rostered ``total_minutes`` and the ``working_staff`` count,
aggregated verbatim from ``roster_week``'s own per-staff
``days`` entries for both weeks — no new counting path. Both
weeks start on a Monday, so entries are keyed BY WEEKDAY
(Monday=0 through Sunday=6), never offset-aligned. An invalid
week start or a missing salon raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from team.availability import _tz
from team.roster_week import StaffWeekRoster, roster_week

__all__ = ["MetricDelta", "ComponentDelta", "RosterWeekDelta",
           "StaffPriorRosterWeek", "WeekdayRosterTotal",
           "WeekdayPriorRosterWeek", "WeekdayRosterWeekDelta",
           "RosterWeekWeekdayDelta", "WEEKDAY_NAMES",
           "PriorRosterWeekReport",
           "PriorRosterWeek", "prior_roster_week_report",
           "prior_roster_week", "prior_period_roster_week",
           "compare_roster_week", "get_prior_roster_week"]
_CENT = Decimal("0.01")
_METRICS = ("total_minutes", "working_days")
_WEEKDAY_METRICS = ("total_minutes", "working_staff")
WEEKDAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
)


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
class WeekdayRosterTotal:
    """One weekday's salon totals, aggregated from ``days``."""

    weekday: int = 0
    weekday_name: str = ""
    day: object = None
    total_minutes: int = 0
    working_staff: int = 0

    date = property(lambda self: self.day)
    staff_count = property(lambda self: self.working_staff)
    working_staff_count = property(lambda self: self.working_staff)

    @property
    def is_working(self): return self.working_staff > 0

    def as_dict(self):
        return {"weekday": self.weekday, "weekday_name": self.weekday_name,
                "day": self.day.isoformat() if self.day else None,
                "total_minutes": self.total_minutes,
                "working_staff": self.working_staff}


@dataclass(frozen=True)
class WeekdayPriorRosterWeek:
    """One weekday's salon totals in both weeks, with changes."""

    weekday: int = 0
    weekday_name: str = ""
    day: object = None
    prior_day: object = None
    current: object = None
    prior: object = None
    total_minutes: MetricDelta = None
    working_staff: MetricDelta = None

    date = property(lambda self: self.day)
    current_date = property(lambda self: self.day)
    prior_date = property(lambda self: self.prior_day)
    staff_count = property(lambda self: self.working_staff)
    working_staff_count = property(lambda self: self.working_staff)

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"weekday": self.weekday, "weekday_name": self.weekday_name,
                "day": iso(self.day), "date": iso(self.day),
                "prior_day": iso(self.prior_day),
                "prior_date": iso(self.prior_day),
                **{m: getattr(self, m).as_dict() for m in _WEEKDAY_METRICS}}


WeekdayRosterWeekDelta = WeekdayPriorRosterWeek
RosterWeekWeekdayDelta = WeekdayPriorRosterWeek


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
    by_weekday: tuple = field(default_factory=tuple)

    salon_id = property(lambda self: getattr(self.salon, "pk", self.salon))
    per_staff = property(lambda self: self.by_staff)
    weekdays = property(lambda self: self.by_weekday)
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

    def for_weekday(self, weekday):
        if isinstance(weekday, str):
            return next((w for w in self.by_weekday
                         if w.weekday_name.lower() == weekday.lower()), None)
        return next((w for w in self.by_weekday if w.weekday == weekday), None)

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"week_start": iso(self.week_start), "week_end": iso(self.week_end),
                "prior_week_start": iso(self.prior_week_start),
                "prior_week_end": iso(self.prior_week_end),
                **{m: getattr(self, m).as_dict() for m in _METRICS},
                "by_staff": [s.as_dict() for s in self.by_staff],
                "by_weekday": [w.as_dict() for w in self.by_weekday]}

    __iter__ = lambda self: iter(self.by_staff)  # noqa: E731
    __len__ = lambda self: len(self.by_staff)  # noqa: E731


PriorRosterWeek = PriorRosterWeekReport


def _weekday_totals(week):
    """Salon totals per weekday, verbatim from per-staff ``days``."""
    totals = []
    for idx in range(7):
        minutes, staff = 0, 0
        for entry in week.entries:
            if idx < len(entry.days):
                day = entry.days[idx]
                minutes += int(day.total_minutes)
                if day.is_working:
                    staff += 1
        totals.append(WeekdayRosterTotal(
            weekday=idx, weekday_name=WEEKDAY_NAMES[idx],
            day=week.week_start + timedelta(days=idx),
            total_minutes=minutes, working_staff=staff))
    return totals


def _weekday_deltas(current, prior):
    cur, pri = _weekday_totals(current), _weekday_totals(prior)
    return tuple(
        WeekdayPriorRosterWeek(
            weekday=idx, weekday_name=WEEKDAY_NAMES[idx],
            day=cur[idx].day, prior_day=pri[idx].day,
            current=cur[idx], prior=pri[idx],
            **{m: _count_delta(m, getattr(cur[idx], m), getattr(pri[idx], m))
               for m in _WEEKDAY_METRICS})
        for idx in range(7))


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
        current=current, prior=prior, by_staff=tuple(by_staff),
        by_weekday=_weekday_deltas(current, prior), **salon_deltas)


prior_roster_week = prior_roster_week_report
prior_period_roster_week = prior_roster_week_report
compare_roster_week = prior_roster_week_report
get_prior_roster_week = prior_roster_week_report
