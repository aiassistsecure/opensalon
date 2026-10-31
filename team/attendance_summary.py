"""Read-only attendance summary service for the team app.

Backend only — no views, templates, or UI. Nothing is mutated:
every figure is derived from ``AttendanceRecord`` rows, the one
source of truth for check-in / check-out events.

A *session* is a check-in paired with the next check-out for the
same staff member: closed sessions count toward worked duration;
open sessions (check-in, no following check-out) are counted
separately with no duration; an orphan check-out pairs with
nothing and is ignored. A session is attributed to the local
date of its check-in in the salon's timezone (``Salon.timezone``,
falling back to UTC); ranges are inclusive whole local days and
``datetime`` arguments are reduced to their local date.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from team.models import AttendanceRecord, StaffMember

__all__ = ["AttendanceSession", "AttendanceSummary", "DayAttendanceSummary",
           "StaffAttendanceSummary", "attendance_summary",
           "attendance_summary_for_range", "get_attendance_summary",
           "summarise_attendance", "summarize_attendance"]


@dataclass(frozen=True)
class AttendanceSession:
    """One paired (or still open) attendance session."""

    staff_member: object
    check_in_at: datetime
    check_out_at: datetime = None
    day: date = None

    @property
    def staff_member_id(self):
        return getattr(self.staff_member, "pk", None)

    @property
    def is_open(self):
        return self.check_out_at is None

    is_closed = property(lambda self: not self.is_open)

    @property
    def duration(self):
        if self.check_out_at is None:
            return timedelta(0)
        return max(self.check_out_at - self.check_in_at, timedelta(0))

    @property
    def total_minutes(self):
        return self.duration // timedelta(minutes=1)


@dataclass(frozen=True)
class StaffAttendanceSummary:
    """Attendance totals for one staff member over a range."""

    staff_member: object
    sessions_count: int = 0
    closed_sessions: int = 0
    open_sessions: int = 0
    total_duration: timedelta = timedelta(0)
    sessions: tuple = ()

    @property
    def staff_member_id(self):
        return getattr(self.staff_member, "pk", None)

    @property
    def display_name(self):
        return getattr(self.staff_member, "display_name", "")

    @property
    def session_count(self):
        return self.sessions_count

    total_sessions = session_count

    @property
    def worked_duration(self):
        return self.total_duration

    duration = worked_duration

    @property
    def total_minutes(self):
        return self.total_duration // timedelta(minutes=1)

    worked_minutes = total_minutes


@dataclass(frozen=True)
class DayAttendanceSummary:
    """Attendance totals for one local date over a range."""

    day: date = None
    sessions_count: int = 0
    closed_sessions: int = 0
    open_sessions: int = 0
    total_duration: timedelta = timedelta(0)
    staff_count: int = 0

    date = property(lambda self: self.day)

    @property
    def session_count(self):
        return self.sessions_count

    total_sessions = session_count

    @property
    def worked_duration(self):
        return self.total_duration

    duration = worked_duration

    @property
    def total_minutes(self):
        return self.total_duration // timedelta(minutes=1)

    worked_minutes = total_minutes


@dataclass(frozen=True)
class AttendanceSummary:
    """Attendance over an inclusive local-date range."""

    salon: object = None
    start_date: date = None
    end_date: date = None
    per_staff: list = field(default_factory=list)
    per_day: list = field(default_factory=list)

    salon_id = property(lambda self: getattr(self.salon, "pk", self.salon))
    entries = property(lambda self: self.per_staff)
    staff = entries
    days = property(lambda self: self.per_day)

    @property
    def by_staff(self):
        return {entry.staff_member_id: entry for entry in self.per_staff}

    @property
    def by_day(self):
        return {entry.day: entry for entry in self.per_day}

    by_date = by_day

    @property
    def sessions_count(self):
        return sum(e.sessions_count for e in self.per_staff)

    session_count = sessions_count
    total_sessions = sessions_count

    @property
    def closed_sessions(self):
        return sum(e.closed_sessions for e in self.per_staff)

    @property
    def open_sessions(self):
        return sum(e.open_sessions for e in self.per_staff)

    @property
    def total_duration(self):
        return sum((e.total_duration for e in self.per_staff), timedelta(0))

    worked_duration = total_duration

    @property
    def total_minutes(self):
        return self.total_duration // timedelta(minutes=1)

    worked_minutes = total_minutes

    def for_staff(self, staff_member):
        return self.by_staff.get(getattr(staff_member, "pk", staff_member))

    def for_day(self, day):
        return self.by_day.get(day)

    __iter__ = lambda self: iter(self.per_staff)
    __len__ = lambda self: len(self.per_staff)


def _tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    raise ValueError("attendance summary needs a date for its range")


def _resolve(args, kwargs):
    """Accept (salon, start, end), (start, end), and kwarg aliases."""
    salon = kwargs.pop("salon", None)
    start = kwargs.pop("start_date", None) or kwargs.pop("start", None) \
        or kwargs.pop("date_from", None)
    end = kwargs.pop("end_date", None) or kwargs.pop("end", None) \
        or kwargs.pop("date_to", None)
    positional = list(args)
    # A leading Salon-like arg (has timezone / staff_members) is salon.
    if positional and salon is None and hasattr(positional[0], "timezone"):
        salon = positional.pop(0)
    if positional and start is None:
        start = positional.pop(0)
    if positional and end is None:
        end = positional.pop(0)
    if kwargs:
        raise TypeError(f"unexpected arguments: {', '.join(kwargs)}")
    if start is None or end is None:
        raise ValueError("attendance summary needs a start and end date")
    return salon, start, end


def _pair_sessions(records, tz):
    """Pair ordered events per staff member into sessions."""
    sessions, open_by_staff = [], {}
    members = {}
    for rec in records:
        members[rec.staff_member_id] = rec.staff_member
        if rec.event_type == AttendanceRecord.EventType.CHECK_IN:
            # A second check-in leaves the earlier one open.
            if rec.staff_member_id in open_by_staff:
                sessions.append(open_by_staff.pop(rec.staff_member_id))
            open_by_staff[rec.staff_member_id] = AttendanceSession(
                staff_member=rec.staff_member,
                check_in_at=rec.recorded_at,
                day=(rec.recorded_at.astimezone(tz) if rec.recorded_at.tzinfo else rec.recorded_at).date(),
            )
        elif rec.event_type == AttendanceRecord.EventType.CHECK_OUT:
            session = open_by_staff.pop(rec.staff_member_id, None)
            if session is not None:
                sessions.append(AttendanceSession(
                    staff_member=session.staff_member,
                    check_in_at=session.check_in_at,
                    check_out_at=rec.recorded_at,
                    day=session.day,
                ))
            # Orphan check-out: no start, so no session/duration.
    sessions.extend(open_by_staff.values())
    return sessions, members


def attendance_summary(*args, **kwargs):
    """Return an :class:`AttendanceSummary` for an inclusive range.

    Call as ``attendance_summary(salon, start_date, end_date)``
    (per-staff entries cover the salon's active staff, zero-filled,
    plus any other member of that salon with sessions in range,
    ordered by display name) or ``attendance_summary(start_date,
    end_date)`` (entries only for staff with sessions in range).
    Read-only: nothing is created, updated, or deleted.
    """
    salon, start, end = _resolve(args, kwargs)
    tz = _tz(salon)
    first, last = _as_date(start, tz), _as_date(end, tz)
    if last < first:
        raise ValueError("range end must not be before range start")
    window_start = datetime.combine(first, time.min, tzinfo=tz)

    records = AttendanceRecord.objects.filter(
        recorded_at__gte=window_start
    ).select_related("staff_member", "staff_member__salon").order_by(
        "staff_member_id", "recorded_at", "id")
    if salon is not None:
        records = records.filter(staff_member__salon=salon)
    sessions, _members = _pair_sessions(list(records), tz)
    sessions = [s for s in sessions if first <= s.day <= last]

    # Per-staff aggregation.
    agg, members = {}, {}
    for session in sessions:
        members[session.staff_member_id] = session.staff_member
        entry = agg.setdefault(session.staff_member_id, {
            "sessions": [], "closed": 0, "open": 0,
            "duration": timedelta(0),
        })
        entry["sessions"].append(session)
        if session.is_open:
            entry["open"] += 1
        else:
            entry["closed"] += 1
            entry["duration"] += session.duration
    if salon is not None:
        for member in StaffMember.objects.filter(salon=salon, active=True):
            members.setdefault(member.pk, member)
    per_staff = [
        StaffAttendanceSummary(
            staff_member=members[pk],
            sessions_count=len(agg.get(pk, {}).get("sessions", ())),
            closed_sessions=agg.get(pk, {}).get("closed", 0),
            open_sessions=agg.get(pk, {}).get("open", 0),
            total_duration=agg.get(pk, {}).get("duration", timedelta(0)),
            sessions=tuple(agg.get(pk, {}).get("sessions", ())),
        )
        for pk in sorted(
            members, key=lambda pk: (members[pk].display_name, pk)
        )
    ]

    # Per-day aggregation, zero-filled for every day in range.
    day_agg = {}
    day = first
    while day <= last:
        day_agg[day] = {"n": 0, "closed": 0, "open": 0,
                        "duration": timedelta(0), "staff": set()}
        day += timedelta(days=1)
    for session in sessions:
        entry = day_agg[session.day]
        entry["n"] += 1
        entry["staff"].add(session.staff_member_id)
        if session.is_open:
            entry["open"] += 1
        else:
            entry["closed"] += 1
            entry["duration"] += session.duration
    per_day = [
        DayAttendanceSummary(
            day=day, sessions_count=v["n"], closed_sessions=v["closed"],
            open_sessions=v["open"], total_duration=v["duration"],
            staff_count=len(v["staff"]),
        )
        for day, v in day_agg.items()
    ]
    return AttendanceSummary(
        salon=salon, start_date=first, end_date=last,
        per_staff=per_staff, per_day=per_day,
    )


summarize_attendance = attendance_summary
summarise_attendance = attendance_summary
attendance_summary_for_range = attendance_summary
get_attendance_summary = attendance_summary
