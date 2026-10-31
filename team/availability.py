"""Roster availability + attendance service for the team app.

Backend only — no views, templates, or UI.

This is the roster layer: given a staff member and a date, it
returns the working intervals programmed in their ``RosterPattern``
rows for that weekday. It deliberately does NOT subtract
appointments — that is ``bookings.availability``'s job, which builds
on rostered time. Nor does it decide online bookability:

* Roster decides *when* someone works.
* ``StaffMember.online_bookable`` decides *whether* they are offered
  through online booking at all.

Those two never conflate here: a member with
``online_bookable=False`` still has rostered intervals (they can be
booked in-salon); the toggle is exposed on the result as a separate
``online_bookable`` flag for callers (e.g. online booking) to apply
as their own filter.

Roster times are wall-clock times in the salon's timezone
(``Salon.timezone``); returned intervals are timezone-aware
datetimes in that zone. Overlapping/touching patterns on the same
weekday merge into one interval; disjoint patterns (a split shift)
stay separate.

Attendance: ``check_in`` / ``check_out`` append an
``AttendanceRecord`` event against the member's schedule. State is
derived from the latest event (``StaffMember.is_checked_in``), so a
duplicate check-in, or a check-out while not checked in, raises
``ValueError`` and records nothing — the event log stays truthful.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from team.models import AttendanceRecord, RosterPattern, ShiftOverride, StaffMember


@dataclass(frozen=True)
class WorkingInterval:
    """One rostered working interval on a date (aware datetimes)."""

    start: datetime
    end: datetime

    @property
    def minutes(self):
        return (self.end - self.start) // timedelta(minutes=1)


@dataclass(frozen=True)
class RosterAvailability:
    """A staff member's rostered availability for one date.

    ``online_bookable`` mirrors ``StaffMember.online_bookable`` as a
    separate flag — it never removes rostered intervals.
    """

    staff_member: StaffMember
    day: date
    online_bookable: bool
    intervals: tuple = ()

    @property
    def staff_member_id(self):
        return self.staff_member.pk

    @property
    def is_working(self):
        return bool(self.intervals)

    @property
    def total_minutes(self):
        return sum(interval.minutes for interval in self.intervals)


def _tz(salon):
    try:
        return ZoneInfo(salon.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_date(day, tz):
    if isinstance(day, datetime):
        return day.astimezone(tz).date() if day.tzinfo else day.date()
    return day


def _merge(intervals):
    ordered = sorted((s, e) for s, e in intervals if e > s)
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def roster_availability(staff_member, day):
    """Roster availability for ``staff_member`` on ``day``.

    Args:
        staff_member: a ``StaffMember`` (inactive members return no
            intervals — they are not rostered for work).
        day: a ``datetime.date``; a datetime is reduced to its date
            in the salon timezone.

    Returns:
        ``RosterAvailability`` with merged aware ``WorkingInterval``s
        from the member's active ``RosterPattern`` rows for that
        weekday, plus the separate ``online_bookable`` flag.
    """
    tz = _tz(staff_member.salon)
    day = _as_date(day, tz)
    intervals = ()
    if staff_member.active:
        # The instance rules its date: a ShiftOverride replaces the
        # perpetual pattern wholesale for this one date.
        override = ShiftOverride.objects.filter(
            staff_member=staff_member, date=day,
        ).first()
        if override is not None:
            windows = [] if override.is_off else [
                (
                    datetime.combine(day, override.start_time, tzinfo=tz),
                    datetime.combine(day, override.end_time, tzinfo=tz),
                )
            ]
            intervals = tuple(
                WorkingInterval(start=s, end=e) for s, e in _merge(windows)
            )
            return RosterAvailability(
                staff_member=staff_member,
                day=day,
                online_bookable=staff_member.online_bookable,
                intervals=intervals,
            )
        patterns = RosterPattern.objects.filter(
            staff_member=staff_member, weekday=day.weekday(), active=True,
        )
        windows = [
            (
                datetime.combine(day, p.start_time, tzinfo=tz),
                datetime.combine(day, p.end_time, tzinfo=tz),
            )
            for p in patterns
        ]
        intervals = tuple(
            WorkingInterval(start=s, end=e) for s, e in _merge(windows)
        )
    return RosterAvailability(
        staff_member=staff_member,
        day=day,
        online_bookable=staff_member.online_bookable,
        intervals=intervals,
    )


def rostered_intervals(staff_member, day):
    """Just the rostered ``WorkingInterval`` tuple for a member/date."""
    return roster_availability(staff_member, day).intervals


def salon_roster(salon, day):
    """``RosterAvailability`` for every active staff member of ``salon``.

    Ordered by display name (StaffMember's default ordering);
    members with no pattern that weekday are included with empty
    intervals so a day view can show who is off.
    """
    return [
        roster_availability(member, day)
        for member in StaffMember.objects.filter(salon=salon, active=True)
    ]


def check_in(staff_member, *, recorded_at=None, note=""):
    """Record a check-in event for ``staff_member``.

    Raises ``ValueError`` (recording nothing) if the member is
    already checked in. ``recorded_at`` defaults to now.
    """
    if staff_member.is_checked_in():
        raise ValueError(f"{staff_member} is already checked in")
    return AttendanceRecord.objects.create(
        staff_member=staff_member,
        event_type=AttendanceRecord.EventType.CHECK_IN,
        recorded_at=recorded_at or timezone.now(),
        note=note,
    )


def check_out(staff_member, *, recorded_at=None, note=""):
    """Record a check-out event for ``staff_member``.

    Raises ``ValueError`` (recording nothing) if the member is not
    currently checked in. ``recorded_at`` defaults to now.
    """
    if not staff_member.is_checked_in():
        raise ValueError(f"{staff_member} is not checked in")
    return AttendanceRecord.objects.create(
        staff_member=staff_member,
        event_type=AttendanceRecord.EventType.CHECK_OUT,
        recorded_at=recorded_at or timezone.now(),
        note=note,
    )
