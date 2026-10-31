"""Availability query: rostered time minus booked appointments.

Pure service module — no views, no UI. Appointments and online
booking may only offer rostered time, so availability starts from
``RosterPattern`` windows for the weekday and subtracts the day's
non-cancelled ``Appointment``s.

There is no break / blocked-time model in the repo yet, so breaks
are not subtracted; when one lands, subtract it alongside the
appointments here.

Timezone: roster times are wall-clock times in the salon's timezone
(``Salon.timezone``); appointment datetimes are aware and compare
directly against the aware roster windows built here.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bookings.models import Appointment, Break
from team.models import RosterPattern, ShiftOverride, StaffMember


@dataclass(frozen=True)
class FreeInterval:
    start: datetime
    end: datetime

    @property
    def minutes(self):
        return (self.end - self.start) // timedelta(minutes=1)


@dataclass(frozen=True)
class StaffAvailability:
    staff_member: StaffMember
    online_bookable: bool
    intervals: tuple

    @property
    def staff_member_id(self):
        return self.staff_member.pk


def _tz(salon):
    try:
        return ZoneInfo(salon.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _merge(intervals):
    """Merge overlapping/touching [start, end) pairs, dropping empties."""
    ordered = sorted((s, e) for s, e in intervals if e > s)
    merged = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract(free, busy):
    """Return merged ``free`` intervals with merged ``busy`` removed."""
    result = list(free)
    for b_start, b_end in busy:
        remaining = []
        for start, end in result:
            if b_end <= start or b_start >= end:
                remaining.append((start, end))
                continue
            if b_start > start:
                remaining.append((start, b_start))
            if b_end < end:
                remaining.append((b_end, end))
        result = [(s, e) for s, e in remaining if e > s]
        if not result:
            break
    return result


def available_slots(salon, day, service=None, *, online_only=False):
    """Free intervals per staff member for ``salon`` on ``day``.

    Args:
        salon: ``saloncore.Salon`` instance.
        day: a ``datetime.date`` (a datetime is reduced to its date
            in the salon timezone).
        service: optional ``saloncore.Service``; when given, only
            intervals at least ``service.total_minutes`` long are
            returned.
        online_only: when True, staff with ``online_bookable=False``
            are excluded entirely; when False (default) they are
            included with ``online_bookable`` flagged False on their
            result, so in-salon booking can still use them.

    Returns:
        list of ``StaffAvailability`` for active staff of the salon
        who have at least one active roster window that weekday
        (possibly with no free intervals left), ordered by staff
        display name (StaffMember's default ordering).
    """
    tz = _tz(salon)
    if isinstance(day, datetime):
        day = day.astimezone(tz).date() if day.tzinfo else day.date()
    day_start = datetime.combine(day, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)

    staff_qs = StaffMember.objects.filter(salon=salon, active=True)
    if online_only:
        staff_qs = staff_qs.filter(online_bookable=True)
    staff = list(staff_qs)

    overrides = {
        o.staff_member_id: o
        for o in ShiftOverride.objects.filter(staff_member__in=staff, date=day)
    }
    patterns = RosterPattern.objects.filter(
        staff_member__in=staff, weekday=day.weekday(), active=True,
    ).select_related("staff_member")
    windows = {}
    for pattern in patterns:
        if pattern.staff_member_id in overrides:
            continue  # the instance rules this date, not the pattern
        windows.setdefault(pattern.staff_member_id, []).append((
            datetime.combine(day, pattern.start_time, tzinfo=tz),
            datetime.combine(day, pattern.end_time, tzinfo=tz),
        ))
    for member_id, override in overrides.items():
        if not override.is_off:
            windows.setdefault(member_id, []).append((
                datetime.combine(day, override.start_time, tzinfo=tz),
                datetime.combine(day, override.end_time, tzinfo=tz),
            ))
    if not windows:
        return []

    appointments = Appointment.objects.filter(
        staff_member_id__in=windows.keys(),
        start__lt=day_end, end__gt=day_start,
    ).exclude(status=Appointment.Status.CANCELLED)
    busy = {}
    for appt in appointments:
        busy.setdefault(appt.staff_member_id, []).append((appt.start, appt.end))
    # Breaks are busy time too: no client, no service, but the
    # span is not bookable — paid or unpaid makes no difference
    # to the math.
    for br in Break.objects.filter(
        staff_member_id__in=windows.keys(),
        start__lt=day_end, end__gt=day_start,
    ):
        busy.setdefault(br.staff_member_id, []).append((br.start, br.end))

    min_minutes = service.total_minutes if service is not None else None
    results = []
    for member in staff:
        if member.pk not in windows:
            continue
        free = _subtract(_merge(windows[member.pk]), _merge(busy.get(member.pk, [])))
        intervals = tuple(
            FreeInterval(start=s, end=e) for s, e in free
            if min_minutes is None or (e - s) >= timedelta(minutes=min_minutes)
        )
        results.append(StaffAvailability(
            staff_member=member,
            online_bookable=member.online_bookable,
            intervals=intervals,
        ))
    return results
