"""Prior for day load (same-weekday comparison).

Backend only, read-only. Built ON TOP of
:func:`bookings.staff_day.staff_day_load` — figures for both
days are that service's verbatim; never recounted. The prior
for a single day is the same weekday one week earlier (a
7-day offset — the salon-natural prior, since the roster runs
on a weekly cycle). Each numeric metric carries current /
prior / delta and ``percent_change`` (Decimal, two places,
ROUND_HALF_UP), ``None`` when prior is zero. ``by_staff`` is
the union of both days, display-name order, zeros / ``None``
times on a missing side. First/last times are carried
verbatim per staff and salon-wide (earliest first start,
latest last start/end). ``per_staff_per_day`` carries the
cross grain: for each member, the source's own figures for
the single current day and its prior day (offset 0 — this
report's windows are one day each), built by calling
``staff_day_load`` once per day per window — the
``team.prior_attendance_summary`` cross construction, a new
CONSTRUCTION over the unchanged source computation, NO new
counting path. Missing salon/date raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from bookings.availability import _tz
from bookings.staff_day import StaffDayLoad, staff_day_load

__all__ = ["MetricDelta", "ComponentDelta", "StaffPriorDayLoad",
           "StaffDayPriorDayLoad", "StaffPerDayPriorDayLoad",
           "StaffDayDayLoadDelta", "PriorDayLoadReport", "PriorDayLoad",
           "prior_day_load_report", "prior_day_load",
           "prior_same_weekday_day_load", "compare_day_load",
           "get_prior_day_load"]
_CENTS = Decimal("0.01")
METRICS = ("appointment_count", "booked_minutes")
TIME_FIELDS = ("first_start", "last_start", "last_end")


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
    def change(self): return self.delta
    @property
    def pct_change(self): return self.percent_change

    def as_dict(self):
        return {"component": self.component, "current": self.current,
                "prior": self.prior, "delta": self.delta,
                "percent_change": self.percent_change}


ComponentDelta = MetricDelta


def _pct_change(current, prior):
    if prior is None or Decimal(int(prior)) == 0:
        return None
    return ((Decimal(int(current)) - Decimal(int(prior)))
            / Decimal(int(prior)) * 100
            ).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    return MetricDelta(name, int(current), int(prior),
                       int(current) - int(prior), _pct_change(current, prior))


def _times(loads):
    firsts = [x.first_start for x in loads if x.first_start]
    lasts = [x.last_start for x in loads if x.last_start]
    ends = [x.last_end for x in loads if x.last_end]
    return (min(firsts) if firsts else None,
            max(lasts) if lasts else None, max(ends) if ends else None)


@dataclass(frozen=True)
class StaffPriorDayLoad:
    staff_member_id: int = None
    staff_name: str = ""
    current: object = None
    prior: object = None
    appointment_count: MetricDelta = None
    booked_minutes: MetricDelta = None
    current_first_start: object = None
    prior_first_start: object = None
    current_last_start: object = None
    prior_last_start: object = None
    current_last_end: object = None
    prior_last_end: object = None

    @property
    def display_name(self): return self.staff_name

    def as_dict(self):
        iso = lambda v: v.isoformat() if v else None  # noqa: E731
        return {"staff_member_id": self.staff_member_id,
                "staff_name": self.staff_name,
                **{m: getattr(self, m).as_dict() for m in METRICS},
                **{f"{p}_{f}": iso(getattr(self, f"{p}_{f}"))
                   for p in ("current", "prior") for f in TIME_FIELDS}}


@dataclass(frozen=True)
class StaffDayPriorDayLoad:
    """One member on the day pair: current day vs prior day."""

    staff_member_id: int = None
    staff_name: str = ""
    day: object = None
    prior_day: object = None
    offset: int = 0
    current: object = None
    prior: object = None
    appointment_count: MetricDelta = None
    booked_minutes: MetricDelta = None
    current_first_start: object = None
    prior_first_start: object = None
    current_last_start: object = None
    prior_last_start: object = None
    current_last_end: object = None
    prior_last_end: object = None

    date = property(lambda self: self.day)
    current_date = property(lambda self: self.day)
    prior_date = property(lambda self: self.prior_day)

    @property
    def display_name(self): return self.staff_name

    @property
    def staff_member(self):
        src = self.current or self.prior
        return src.staff_member if src is not None else None

    def as_dict(self):
        iso = lambda v: v.isoformat() if v else None  # noqa: E731
        return {"staff_member_id": self.staff_member_id,
                "staff_name": self.staff_name,
                "day": iso(self.day), "date": iso(self.day),
                "current_date": iso(self.day),
                "prior_day": iso(self.prior_day),
                "prior_date": iso(self.prior_day),
                "offset": self.offset,
                **{m: getattr(self, m).as_dict() for m in METRICS},
                **{f"{p}_{f}": iso(getattr(self, f"{p}_{f}"))
                   for p in ("current", "prior") for f in TIME_FIELDS}}


StaffPerDayPriorDayLoad = StaffDayPriorDayLoad
StaffDayDayLoadDelta = StaffDayPriorDayLoad


@dataclass(frozen=True)
class PriorDayLoadReport:
    salon: object = None
    date: object = None
    prior_date: object = None
    current: object = None
    prior: object = None
    appointment_count: MetricDelta = None
    booked_minutes: MetricDelta = None
    current_first_start: object = None
    prior_first_start: object = None
    current_last_start: object = None
    prior_last_start: object = None
    current_last_end: object = None
    prior_last_end: object = None
    by_staff: tuple = field(default_factory=tuple)
    per_staff_per_day: tuple = field(default_factory=tuple)

    by_staff_per_day = property(lambda self: self.per_staff_per_day)
    staff_per_day = by_staff_per_day

    @property
    def previous(self): return self.prior
    @property
    def start_date(self): return self.date
    @property
    def end_date(self): return self.date
    @property
    def prior_start_date(self): return self.prior_date
    @property
    def prior_end_date(self): return self.prior_date
    @property
    def day(self): return self.date

    def for_staff_day(self, staff_member, day):
        key = getattr(staff_member, "pk", staff_member)
        dkey = day.date() if isinstance(day, datetime) else day
        return next((e for e in self.per_staff_per_day
                     if e.staff_member_id == key and e.day == dkey), None)

    for_staff_on_day = for_staff_day

    def as_dict(self):
        iso = lambda v: v.isoformat() if v else None  # noqa: E731
        cross = [e.as_dict() for e in self.per_staff_per_day]
        return {"date": iso(self.date), "prior_date": iso(self.prior_date),
                "start_date": iso(self.date), "end_date": iso(self.date),
                "prior_start_date": iso(self.prior_date),
                "prior_end_date": iso(self.prior_date),
                **{m: getattr(self, m).as_dict() for m in METRICS},
                **{f"{p}_{f}": iso(getattr(self, f"{p}_{f}"))
                   for p in ("current", "prior") for f in TIME_FIELDS},
                "by_staff": [s.as_dict() for s in self.by_staff],
                "per_staff_per_day": cross, "by_staff_per_day": cross}


PriorDayLoad = PriorDayLoadReport


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _per_staff_per_day(salon, current_date, prior_date):
    """Cross grain: per member, on the current/prior day pair.

    A new CONSTRUCTION over the unchanged source computation:
    ``staff_day_load`` is called once per day per window (this
    report's windows are one day each, offset 0) and its own
    per-staff rows are paired — no new counting path. A member
    present on one side only is zero-filled on the other, as
    the ``by_staff`` grain does. Ordered by display name then
    id (the ``by_staff`` order).
    """
    cur = {x.staff_member_id: x for x in staff_day_load(salon, current_date)}
    pri = {x.staff_member_id: x for x in staff_day_load(salon, prior_date)}
    members = {}
    for src in (cur, pri):
        for key, entry in src.items():
            members[key] = entry.staff_member
    out = []
    for key in sorted(members, key=lambda k: (members[k].display_name, k)):
        member = members[key]
        c = cur.get(key) or StaffDayLoad(staff_member=member)
        p = pri.get(key) or StaffDayLoad(staff_member=member)
        out.append(StaffDayPriorDayLoad(
            staff_member_id=key, staff_name=member.display_name,
            day=current_date, prior_day=prior_date, offset=0,
            current=c, prior=p,
            **{m: _count_delta(m, getattr(c, m), getattr(p, m))
               for m in METRICS},
            current_first_start=c.first_start, prior_first_start=p.first_start,
            current_last_start=c.last_start, prior_last_start=p.last_start,
            current_last_end=c.last_end, prior_last_end=p.last_end))
    return tuple(out)


def prior_day_load_report(salon, day=None, **kwargs):
    """Return the day-load comparison for ``salon`` on ``day``.

    Prior day is ``day - 7 days`` (same weekday). ``day`` may
    also be passed as ``date=`` / ``date_from=`` / ``start_date=``.
    Raises ``ValueError`` if salon or date is missing/unparseable.
    """
    if day is None:
        day = (kwargs.pop("date", None) or kwargs.pop("date_from", None)
               or kwargs.pop("start_date", None) or kwargs.pop("start", None))
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    if salon is None:
        raise ValueError("A salon is required.")
    if day is None:
        raise ValueError("A date is required.")
    try:
        current_date = _as_date(day, _tz(salon))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid date {day!r}.") from exc
    prior_date = current_date - timedelta(days=7)
    current, prior = (staff_day_load(salon, current_date),
                      staff_day_load(salon, prior_date))
    cur = {x.staff_member_id: x for x in current}
    pri = {x.staff_member_id: x for x in prior}
    members = {}
    for src in (current, prior):
        for x in src:
            members[x.staff_member_id] = x.staff_member
    by_staff = []
    for key in sorted(members, key=lambda k: (members[k].display_name, k)):
        member = members[key]
        c = cur.get(key) or StaffDayLoad(staff_member=member)
        p = pri.get(key) or StaffDayLoad(staff_member=member)
        by_staff.append(StaffPriorDayLoad(
            staff_member_id=key, staff_name=member.display_name,
            current=c, prior=p,
            **{m: _count_delta(m, getattr(c, m), getattr(p, m))
               for m in METRICS},
            current_first_start=c.first_start, prior_first_start=p.first_start,
            current_last_start=c.last_start, prior_last_start=p.last_start,
            current_last_end=c.last_end, prior_last_end=p.last_end))
    c_first, c_last, c_end = _times(current)
    p_first, p_last, p_end = _times(prior)
    return PriorDayLoadReport(
        salon=salon, date=current_date, prior_date=prior_date,
        current=current, prior=prior,
        appointment_count=_count_delta(
            "appointment_count", sum(x.appointment_count for x in current),
            sum(x.appointment_count for x in prior)),
        booked_minutes=_count_delta(
            "booked_minutes", sum(x.booked_minutes for x in current),
            sum(x.booked_minutes for x in prior)),
        current_first_start=c_first, prior_first_start=p_first,
        current_last_start=c_last, prior_last_start=p_last,
        current_last_end=c_end, prior_last_end=p_end,
        by_staff=tuple(by_staff),
        per_staff_per_day=_per_staff_per_day(salon, current_date, prior_date))


prior_day_load = prior_day_load_report
prior_same_weekday_day_load = prior_day_load_report
compare_day_load = prior_day_load_report
get_prior_day_load = prior_day_load_report
