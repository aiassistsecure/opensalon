"""Prior-period comparison for the attendance summary.

Backend only, read-only, built ON TOP of
:func:`team.attendance_summary.attendance_summary` — figures for
both windows are that service's verbatim. For an inclusive current
window of ``length`` days, the prior period is the equal-length
window immediately before it. Each metric carries ``current``,
``prior``, ``delta`` and ``percent_change`` (Decimal, 2dp,
ROUND_HALF_UP), ``None`` when prior is zero. Headline fields are
the summary's own: ``sessions_count``, ``closed_sessions``,
``open_sessions`` and ``total_minutes`` (the service's int derived
from ``total_duration``). ``by_staff`` is the union of both
windows' rows, ordered by display name then id. ``per_day``
carries the source's per-day breakdown too: entries are
offset-aligned between the windows (day 1 vs day 1, day 2 vs
day 2, …, following ``prior_campaign_send_totals``' by_day
alignment), taken verbatim from ``attendance_summary``'s own
``per_day`` entries for both windows — no new counting. If the
two ``per_day`` lists ever differ in length, the shorter side
is zero-filled at that offset (the source zero-fills every day
in range, so a missing entry is a zero entry dated by window
start + offset). ``per_staff_per_day`` carries the cross grain:
for each member and each offset-aligned day pair, the source's
own ``per_staff`` figures for that single day (the same
sessions / closed / open counts and worked minutes the
``per_staff`` rows carry), built by calling
``attendance_summary`` once per day per window — this is a new
CONSTRUCTION over the unchanged source computation, NO new
counting path. Rows present on one side only zero-fill, as
the existing ``per_staff`` grain does. A reversed window,
missing salon, or missing date raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from team.attendance_summary import (DayAttendanceSummary,
                                     StaffAttendanceSummary,
                                     attendance_summary)
from team.availability import _tz

__all__ = ["MetricDelta", "ComponentDelta", "AttendanceDelta",
           "StaffPriorAttendanceSummary", "DayPriorAttendanceSummary",
           "DayAttendanceDelta", "StaffDayPriorAttendanceSummary",
           "StaffPerDayPriorAttendanceSummary", "StaffDayAttendanceDelta",
           "PriorAttendanceSummaryReport",
           "PriorAttendanceSummary", "prior_attendance_summary_report",
           "prior_attendance_summary", "prior_period_attendance_summary",
           "compare_attendance_summary", "get_prior_attendance_summary"]
_CENT = Decimal("0.01")
_METRICS = ("sessions_count", "closed_sessions", "open_sessions", "total_minutes")
_DAY_METRICS = _METRICS + ("staff_count",)


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
AttendanceDelta = MetricDelta


def _pct_change(current, prior):
    if prior is None or Decimal(prior) == 0:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior) * 100
            ).quantize(_CENT, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior),
                       int(current) - int(prior), _pct_change(current, prior))


def _empty_staff(member):
    return StaffAttendanceSummary(staff_member=member)


def _empty_day(day):
    return DayAttendanceSummary(day=day)


@dataclass(frozen=True)
class DayPriorAttendanceSummary:
    """One offset-aligned per-day pair: current day vs prior day."""

    day: object = None
    prior_day: object = None
    offset: int = 0
    current: object = None
    prior: object = None
    sessions_count: MetricDelta = None
    closed_sessions: MetricDelta = None
    open_sessions: MetricDelta = None
    total_minutes: MetricDelta = None
    staff_count: MetricDelta = None

    date = property(lambda self: self.day)
    current_date = property(lambda self: self.day)
    prior_date = property(lambda self: self.prior_day)

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"day": iso(self.day), "date": iso(self.day),
                "current_date": iso(self.day),
                "prior_day": iso(self.prior_day),
                "prior_date": iso(self.prior_day),
                "offset": self.offset,
                **{m: getattr(self, m).as_dict() for m in _DAY_METRICS}}


DayAttendanceDelta = DayPriorAttendanceSummary


@dataclass(frozen=True)
class StaffPriorAttendanceSummary:
    staff_member: object = None
    current: object = None
    prior: object = None
    sessions_count: MetricDelta = None
    closed_sessions: MetricDelta = None
    open_sessions: MetricDelta = None
    total_minutes: MetricDelta = None

    @property
    def staff_member_id(self): return self.staff_member.pk if self.staff_member else None
    @property
    def staff_name(self): return self.staff_member.display_name if self.staff_member else ""
    display_name = staff_name

    def as_dict(self):
        return {"staff_member_id": self.staff_member_id, "staff_name": self.staff_name,
                **{m: getattr(self, m).as_dict() for m in _METRICS}}


@dataclass(frozen=True)
class StaffDayPriorAttendanceSummary:
    """One member on one offset-aligned day pair: current vs prior."""

    staff_member: object = None
    day: object = None
    prior_day: object = None
    offset: int = 0
    current: object = None
    prior: object = None
    sessions_count: MetricDelta = None
    closed_sessions: MetricDelta = None
    open_sessions: MetricDelta = None
    total_minutes: MetricDelta = None

    date = property(lambda self: self.day)
    current_date = property(lambda self: self.day)
    prior_date = property(lambda self: self.prior_day)

    @property
    def staff_member_id(self): return self.staff_member.pk if self.staff_member else None
    @property
    def staff_name(self): return self.staff_member.display_name if self.staff_member else ""
    display_name = staff_name

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"staff_member_id": self.staff_member_id,
                "staff_name": self.staff_name,
                "day": iso(self.day), "date": iso(self.day),
                "current_date": iso(self.day),
                "prior_day": iso(self.prior_day),
                "prior_date": iso(self.prior_day),
                "offset": self.offset,
                **{m: getattr(self, m).as_dict() for m in _METRICS}}


StaffPerDayPriorAttendanceSummary = StaffDayPriorAttendanceSummary
StaffDayAttendanceDelta = StaffDayPriorAttendanceSummary


@dataclass(frozen=True)
class PriorAttendanceSummaryReport:
    salon: object = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    sessions_count: MetricDelta = None
    closed_sessions: MetricDelta = None
    open_sessions: MetricDelta = None
    total_minutes: MetricDelta = None
    by_staff: tuple = field(default_factory=tuple)
    per_day: tuple = field(default_factory=tuple)
    per_staff_per_day: tuple = field(default_factory=tuple)

    salon_id = property(lambda self: getattr(self.salon, "pk", self.salon))
    per_staff = property(lambda self: self.by_staff)
    entries = per_staff
    staff = per_staff
    by_day = property(lambda self: self.per_day)
    by_staff_per_day = property(lambda self: self.per_staff_per_day)
    staff_per_day = by_staff_per_day

    @property
    def previous(self): return self.prior
    @property
    def days(self): return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    @property
    def length(self): return self.days

    def for_staff(self, staff_member):
        key = getattr(staff_member, "pk", staff_member)
        return next((s for s in self.by_staff if s.staff_member_id == key), None)

    def for_day(self, day):
        key = day.date() if isinstance(day, datetime) else day
        return next((d for d in self.per_day if d.day == key), None)

    def for_staff_day(self, staff_member, day):
        key = getattr(staff_member, "pk", staff_member)
        dkey = day.date() if isinstance(day, datetime) else day
        return next((e for e in self.per_staff_per_day
                     if e.staff_member_id == key and e.day == dkey), None)

    for_staff_on_day = for_staff_day

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        per_day = [d.as_dict() for d in self.per_day]
        cross = [e.as_dict() for e in self.per_staff_per_day]
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                **{m: getattr(self, m).as_dict() for m in _METRICS},
                "by_staff": [s.as_dict() for s in self.by_staff],
                "per_day": per_day, "by_day": per_day,
                "per_staff_per_day": cross, "by_staff_per_day": cross}

    __iter__ = lambda self: iter(self.by_staff)  # noqa: E731
    __len__ = lambda self: len(self.by_staff)  # noqa: E731


PriorAttendanceSummary = PriorAttendanceSummaryReport


def _deltas(current, prior, metrics=_METRICS):
    return {name: _count_delta(name, getattr(current, name), getattr(prior, name))
            for name in metrics}


def _per_day_deltas(current, prior, first, prior_first):
    """Offset-align both windows' ``per_day`` entries, verbatim.

    Index ``i`` of the current list pairs with index ``i`` of
    the prior list; a side missing at an offset is zero-filled
    with an entry dated window-start + offset.
    """
    cur_days, pri_days = list(current.per_day), list(prior.per_day)
    out = []
    for offset in range(max(len(cur_days), len(pri_days))):
        cur = cur_days[offset] if offset < len(cur_days) else \
            _empty_day(first + timedelta(days=offset))
        pri = pri_days[offset] if offset < len(pri_days) else \
            _empty_day(prior_first + timedelta(days=offset))
        out.append(DayPriorAttendanceSummary(
            day=cur.day, prior_day=pri.day, offset=offset,
            current=cur, prior=pri,
            **_deltas(cur, pri, _DAY_METRICS)))
    return tuple(out)


def _per_staff_per_day(salon, first, prior_first, length):
    """Cross grain: per member, per offset-aligned day pair.

    A new CONSTRUCTION over the unchanged source computation:
    ``attendance_summary`` is called once per day per window
    and its own single-day ``per_staff`` rows are paired at
    each offset — no new counting path. A member present on
    one side only is zero-filled on the other, as the
    existing ``per_staff`` grain does. Ordered by offset,
    then display name then id (the ``by_staff`` order).
    """
    out = []
    for offset in range(length):
        cur_day = first + timedelta(days=offset)
        pri_day = prior_first + timedelta(days=offset)
        cur = {e.staff_member_id: e for e in
               attendance_summary(salon, cur_day, cur_day).per_staff}
        pri = {e.staff_member_id: e for e in
               attendance_summary(salon, pri_day, pri_day).per_staff}
        members = {}
        for src in (cur, pri):
            for key, entry in src.items():
                members[key] = entry.staff_member
        for key in sorted(members, key=lambda k: (members[k].display_name, k)):
            cur_e = cur.get(key) or _empty_staff(members[key])
            pri_e = pri.get(key) or _empty_staff(members[key])
            out.append(StaffDayPriorAttendanceSummary(
                staff_member=members[key], day=cur_day, prior_day=pri_day,
                offset=offset, current=cur_e, prior=pri_e,
                **_deltas(cur_e, pri_e)))
    return tuple(out)


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def prior_attendance_summary_report(salon, date_from=None, date_to=None, *,
                                    start_date=None, end_date=None, **kwargs):
    """Return the attendance summary comparison for ``salon``.

    Call as ``(salon, first, last)``, ``(salon, day)`` for one day,
    or with ``start_date=`` / ``end_date=`` aliases (``start`` /
    ``end`` / ``since`` / ``until`` also accepted). Raises
    ``ValueError`` if the salon or a date is missing, or the
    window is reversed.
    """
    if salon is None:
        raise ValueError("prior attendance summary comparison needs a salon")
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
    current = attendance_summary(salon, first, last)
    prior = attendance_summary(salon, p_start, p_end)
    cur = {e.staff_member_id: e for e in current.per_staff}
    pri = {e.staff_member_id: e for e in prior.per_staff}
    members = {}
    for src in (current.per_staff, prior.per_staff):
        for e in src:
            members[e.staff_member_id] = e.staff_member
    by_staff = tuple(
        StaffPriorAttendanceSummary(
            staff_member=members[key],
            current=cur.get(key) or _empty_staff(members[key]),
            prior=pri.get(key) or _empty_staff(members[key]),
            **_deltas(cur.get(key) or _empty_staff(members[key]),
                      pri.get(key) or _empty_staff(members[key])))
        for key in sorted(members, key=lambda k: (members[k].display_name, k)))
    return PriorAttendanceSummaryReport(
        salon=salon, start_date=first, end_date=last, prior_start_date=p_start,
        prior_end_date=p_end, current=current, prior=prior,
        by_staff=by_staff, per_day=_per_day_deltas(current, prior, first, p_start),
        per_staff_per_day=_per_staff_per_day(salon, first, p_start, length),
        **_deltas(current, prior))


prior_attendance_summary = prior_attendance_summary_report
prior_period_attendance_summary = prior_attendance_summary_report
compare_attendance_summary = prior_attendance_summary_report
get_prior_attendance_summary = prior_attendance_summary_report
