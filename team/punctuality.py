"""Punctuality report service for the team app.

Backend only — no views, templates, or UI. Read-only.

For a salon and an inclusive date window (whole local days in
the salon's timezone), per staff member this compares recorded
check-ins against rostered shift starts:

* Rostered shifts come from
  :func:`team.availability.roster_availability` — the one
  roster/availability resolution (patterns + overrides); no
  roster logic is duplicated here. One *shift* is one rostered
  day: a day with at least one rostered interval counts once,
  and its shift start is the start of its first (earliest)
  interval, so a split shift is still a single shift.
* The check-in evaluated for a shift is the member's earliest
  ``check_in`` :class:`~team.models.AttendanceRecord` on that
  same local date (salon timezone). A check-in at or before the
  shift start is on time; a check-in after it is late by the
  whole minutes between start and check-in (floor, matching the
  team app's ``total_minutes`` convention). A rostered day with
  no check-in at all is *missed*: it counts in
  ``shifts_considered`` and ``missed_count`` but is neither on
  time nor late and contributes no late minutes.

Choice on staff coverage: staff with no rostered shifts in the
window are EXCLUDED from the report (punctuality is undefined
for them) — unlike the variance/attendance summaries, this
report does not zero-fill. Only active staff are considered,
because ``roster_availability`` rosters no time for inactive
members. Entries are ordered by display name, then id.

``total_late_minutes`` is an int (team convention);
``average_late_minutes`` is a ``Decimal`` quantised to two
places — total late minutes per *late* shift, ``Decimal("0.00")``
when no shift is late.
"""
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from team.availability import _as_date, _tz, roster_availability
from team.models import AttendanceRecord, StaffMember

__all__ = ["PunctualityReport", "StaffPunctuality",
           "get_punctuality_report", "punctuality_report",
           "team_punctuality"]

_CENT = Decimal("0.01")
_ZERO_AVG = Decimal("0.00")


def _average(total_late, late_count):
    if not late_count:
        return _ZERO_AVG
    return (Decimal(total_late) / late_count).quantize(
        _CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class StaffPunctuality:
    """Punctuality totals for one staff member over a window."""

    staff_member: object
    shifts_considered: int = 0
    on_time_count: int = 0
    late_count: int = 0
    missed_count: int = 0
    total_late_minutes: int = 0

    @property
    def staff_member_id(self):
        return getattr(self.staff_member, "pk", None)

    @property
    def display_name(self):
        return getattr(self.staff_member, "display_name", "")

    staff_name = display_name
    shifts = property(lambda self: self.shifts_considered)

    @property
    def average_late_minutes(self):
        return _average(self.total_late_minutes, self.late_count)

    average_late = average_late_minutes


@dataclass(frozen=True)
class PunctualityReport:
    """Punctuality over an inclusive local-date range."""

    salon: object = None
    start_date: object = None
    end_date: object = None
    per_staff: list = field(default_factory=list)

    salon_id = property(lambda self: getattr(self.salon, "pk", self.salon))
    entries = property(lambda self: self.per_staff)
    staff = entries

    @property
    def by_staff(self):
        return {e.staff_member_id: e for e in self.per_staff}

    def for_staff(self, staff_member):
        return self.by_staff.get(getattr(staff_member, "pk", staff_member))

    @property
    def shifts_considered(self):
        return sum(e.shifts_considered for e in self.per_staff)

    @property
    def on_time_count(self):
        return sum(e.on_time_count for e in self.per_staff)

    @property
    def late_count(self):
        return sum(e.late_count for e in self.per_staff)

    @property
    def missed_count(self):
        return sum(e.missed_count for e in self.per_staff)

    @property
    def total_late_minutes(self):
        return sum(e.total_late_minutes for e in self.per_staff)

    @property
    def average_late_minutes(self):
        return _average(self.total_late_minutes, self.late_count)

    __iter__ = lambda self: iter(self.per_staff)
    __len__ = lambda self: len(self.per_staff)


def punctuality_report(salon, start_date, end_date):
    """Return a :class:`PunctualityReport` for ``salon``/window.

    Raises ``ValueError`` for a missing salon, missing dates,
    or a reversed window. Read-only.
    """
    if salon is None:
        raise ValueError("punctuality report needs a salon")
    if start_date is None or end_date is None:
        raise ValueError("punctuality report needs a start and end date")
    tz = _tz(salon)
    first, last = _as_date(start_date, tz), _as_date(end_date, tz)
    if last < first:
        raise ValueError("range end must not be before range start")

    # Earliest check-in per (staff, local date) across the window.
    window_start = datetime.combine(first, time.min, tzinfo=tz)
    window_end = datetime.combine(
        last + timedelta(days=1), time.min, tzinfo=tz)
    earliest = {}
    records = AttendanceRecord.objects.filter(
        staff_member__salon=salon,
        event_type=AttendanceRecord.EventType.CHECK_IN,
        recorded_at__gte=window_start, recorded_at__lt=window_end,
    ).order_by("staff_member_id", "recorded_at", "id")
    for rec in records:
        local = rec.recorded_at
        day = (local.astimezone(tz) if local.tzinfo else local).date()
        key = (rec.staff_member_id, day)
        if key not in earliest:
            earliest[key] = rec.recorded_at

    days = []
    day = first
    while day <= last:
        days.append(day)
        day += timedelta(days=1)

    per_staff = []
    members = StaffMember.objects.filter(salon=salon, active=True)
    for member in members:
        shifts = on_time = late = missed = total_late = 0
        for d in days:
            avail = roster_availability(member, d)
            if not avail.is_working:
                continue
            shifts += 1
            check_in_at = earliest.get((member.pk, d))
            if check_in_at is None:
                missed += 1
            elif check_in_at <= avail.intervals[0].start:
                on_time += 1
            else:
                late += 1
                total_late += (
                    check_in_at - avail.intervals[0].start
                ) // timedelta(minutes=1)
        if shifts == 0:
            continue  # No rostered shifts in window: excluded.
        per_staff.append(StaffPunctuality(
            staff_member=member, shifts_considered=shifts,
            on_time_count=on_time, late_count=late,
            missed_count=missed, total_late_minutes=total_late,
        ))
    return PunctualityReport(salon=salon, start_date=first,
                             end_date=last, per_staff=per_staff)


get_punctuality_report = punctuality_report
team_punctuality = punctuality_report
