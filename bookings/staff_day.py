"""Per-staff day load service.

Pure service module — no views, no templates, no UI. Derived only
from ``Appointment`` records (one source of truth); nothing new is
stored.

For one local day, each staff member's load is::

    StaffDayLoad(
        staff_member,        # team.StaffMember instance
        staff_member_id,     # its pk (property)
        display_name,        # staff_member.display_name (property)
        appointment_count,   # non-cancelled appointments that day
        booked_minutes,      # sum of (end - start), whole minutes
        first_start,         # earliest appointment start, or None
        last_start,          # latest appointment start, or None
        last_end,            # latest appointment end, or None
    )

``first_appointment_time`` / ``last_appointment_time`` are aliases
for ``first_start`` / ``last_end``.

Cancelled appointments are excluded (they do not occupy the book —
the same rule :mod:`bookings.daybook` and
:mod:`bookings.availability` apply). Every other status counts.

Timezone handling follows :mod:`bookings.daybook`: when a salon is
given, the local day is in the salon's timezone (via
``bookings.availability._tz``); a datetime ``day`` is reduced to
its date in that timezone. When no salon is given, the local day
is in ``settings.TIME_ZONE`` (the deployment timezone; salon
timezones default from it), likewise aware. Day membership is by
overlap, as in the day book: ``start < day_end and end > day_start``.
Booked minutes are the literal sum of ``end - start`` per counted
appointment, as specified, not a day-clipped sum.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings

from bookings.availability import _tz
from bookings.models import Appointment
from team.models import StaffMember

__all__ = ["StaffDayLoad", "staff_day_load", "staff_load_for_day"]


@dataclass(frozen=True)
class StaffDayLoad:
    staff_member: StaffMember
    appointment_count: int = 0
    booked_minutes: int = 0
    first_start: datetime = None
    last_start: datetime = None
    last_end: datetime = None

    @property
    def staff_member_id(self):
        return self.staff_member.pk

    @property
    def display_name(self):
        return self.staff_member.display_name

    @property
    def first_appointment_time(self):
        return self.first_start

    @property
    def last_appointment_time(self):
        return self.last_end


def _settings_tz():
    try:
        return ZoneInfo(settings.TIME_ZONE or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _bounds(day, tz):
    if isinstance(day, datetime):
        day = day.astimezone(tz).date() if day.tzinfo else day.date()
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def staff_day_load(salon_or_day, day=None):
    """Return per-staff load for one local day.

    Call either ``staff_day_load(salon, day)`` — one entry per
    active staff member of ``salon`` (including zero-load staff,
    so an empty day still lists them), ordered by display name —
    or ``staff_day_load(day)`` — one entry per staff member with a
    counted appointment that day (an empty day returns ``[]``),
    in ``settings.TIME_ZONE``, ordered by display name.

    Args:
        salon_or_day: a ``saloncore.Salon`` (with ``day`` given)
            or a ``datetime.date`` / aware datetime.
        day: a ``datetime.date`` (a datetime is reduced to its
            date in the applicable timezone).
    """
    if day is None:
        salon, day, tz = None, salon_or_day, _settings_tz()
        staff = None
    else:
        salon, tz = salon_or_day, _tz(salon_or_day)
        staff = list(StaffMember.objects.filter(salon=salon, active=True))
    day_start, day_end = _bounds(day, tz)

    appointments = (
        Appointment.objects.filter(start__lt=day_end, end__gt=day_start)
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("staff_member")
        .order_by("start", "pk")
    )
    if staff is not None:
        appointments = appointments.filter(staff_member__in=staff)

    # pk -> [count, minutes, first_start, last_start, last_end, member]
    agg = {}
    for appt in appointments:
        minutes = (appt.end - appt.start) // timedelta(minutes=1)
        entry = agg.get(appt.staff_member_id)
        if entry is None:
            agg[appt.staff_member_id] = [
                1, minutes, appt.start, appt.start, appt.end,
                appt.staff_member,
            ]
        else:
            entry[0] += 1
            entry[1] += minutes
            entry[2] = min(entry[2], appt.start)
            entry[3] = max(entry[3], appt.start)
            entry[4] = max(entry[4], appt.end)

    def _load(member):
        entry = agg.get(member.pk)
        if entry is None:
            return StaffDayLoad(staff_member=member)
        count, minutes, first, last_start, last_end, _ = entry
        return StaffDayLoad(
            staff_member=member, appointment_count=count,
            booked_minutes=minutes, first_start=first,
            last_start=last_start, last_end=last_end,
        )

    if staff is not None:
        return [_load(member) for member in staff]
    members = sorted(
        (entry[5] for entry in agg.values()),
        key=lambda m: (m.display_name, m.pk),
    )
    return [_load(member) for member in members]


def staff_load_for_day(salon, day):
    """Explicit-salon alias for ``staff_day_load(salon, day)``."""
    return staff_day_load(salon, day)
