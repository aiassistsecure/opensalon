"""Read-only availability outlook for online booking.

Backend only — no views, templates, or branding. Pure service:
nothing is created, updated, or deleted.

For each online-bookable staff member of a salon this counts the
bookable start times over the next ``days`` days (default
:data:`DEFAULT_OUTLOOK_DAYS`), broken down per day.

Slot logic is NOT reimplemented here. Every count comes from
:func:`onlinebooking.slots.available_slots`, which in turn
delegates to the single availability source of truth
(``bookings.availability``): rostered time from the staff
member's active ``RosterPattern`` windows, minus the day's
non-cancelled appointments, stepped at the slots grid, with a
start offered only when the whole service fits.

The per-staff online-booking toggle is authoritative here too:

* Staff with ``online_bookable=False`` are EXCLUDED entirely —
  they do not appear in the result at all (the slots service
  would return ``[]`` for them anyway; excluding them up front
  keeps an outlook from presenting them as merely ``0``-slot
  staff).
* Inactive staff are likewise excluded.
* Active, online-bookable staff DO appear even with zero slots
  (unrostered, fully booked, or no interval long enough) — a
  zero is real outlook information, distinct from not being
  offered online at all.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.utils import timezone

from bookings.availability import _tz
from onlinebooking.slots import SLOT_STEP_MINUTES, available_slots
from team.models import StaffMember

__all__ = [
    "DEFAULT_OUTLOOK_DAYS",
    "DayOutlook",
    "StaffOutlook",
    "availability_outlook",
    "staff_availability_outlook",
    "outlook",
]

#: Default outlook window, in days (today plus the next six).
DEFAULT_OUTLOOK_DAYS = 7


@dataclass(frozen=True)
class DayOutlook:
    """Bookable-slot count for one staff member on one day."""

    date: date
    slot_count: int = 0
    slots: tuple = ()

    @property
    def first_slot(self):
        return self.slots[0] if self.slots else None

    @property
    def last_slot(self):
        return self.slots[-1] if self.slots else None

    @property
    def has_availability(self):
        return self.slot_count > 0


@dataclass(frozen=True)
class StaffOutlook:
    """Bookable-slot outlook for one staff member over a window."""

    staff_member: StaffMember
    days: tuple = ()
    total_slots: int = 0

    @property
    def staff_member_id(self):
        return self.staff_member.pk

    @property
    def display_name(self):
        return self.staff_member.display_name

    @property
    def staff_display_name(self):
        """Alias for :attr:`display_name`."""
        return self.staff_member.display_name

    @property
    def slot_count(self):
        """Alias for :attr:`total_slots`."""
        return self.total_slots

    @property
    def days_with_availability(self):
        return sum(1 for day in self.days if day.slot_count > 0)

    @property
    def first_available_date(self):
        for day in self.days:
            if day.slot_count > 0:
                return day.date
        return None

    @property
    def first_slot(self):
        for day in self.days:
            if day.slots:
                return day.slots[0]
        return None


def _start_date(salon, start_date):
    if start_date is None:
        return timezone.localdate()
    if isinstance(start_date, datetime):
        if start_date.tzinfo is not None:
            return start_date.astimezone(_tz(salon)).date()
        return start_date.date()
    return start_date


def availability_outlook(salon, service_duration, *, days=DEFAULT_OUTLOOK_DAYS,
                         start_date=None, step_minutes=SLOT_STEP_MINUTES):
    """Count bookable slots per online-bookable staff member.

    Args:
        salon: a ``saloncore.Salon`` instance the result is
            scoped to.
        service_duration: length of the service to fit — minutes
            (``int``/``float``), a ``timedelta``, or a service-like
            object with ``total_minutes`` — passed unchanged to
            :func:`onlinebooking.slots.available_slots`, whose
            validation (positive duration, positive step) applies.
        days: window size in days, starting at ``start_date``
            (keyword-only, default :data:`DEFAULT_OUTLOOK_DAYS`).
            A non-positive value returns ``[]``.
        start_date: first day of the window — a ``datetime.date``
            (an aware datetime is reduced to its date in the
            salon timezone). Defaults to today (local date).
        step_minutes: grid spacing passed to the slots service.

    Returns:
        A list of :class:`StaffOutlook`, one per active staff
        member of ``salon`` with ``online_bookable=True``,
        ordered by display name (``StaffMember``'s default
        ordering). Each row's ``total_slots`` equals the sum of
        its per-day ``slot_count`` values. Empty when ``salon``
        is ``None``, ``days`` is non-positive, or the salon has
        no active online-bookable staff.
    """
    if salon is None or days is None or days <= 0:
        return []
    first_day = _start_date(salon, start_date)
    window = [first_day + timedelta(days=offset) for offset in range(days)]
    staff = StaffMember.objects.filter(
        salon=salon, active=True, online_bookable=True
    )
    results = []
    for member in staff:
        day_rows = []
        total = 0
        for day in window:
            slots = available_slots(
                member, day, service_duration, step_minutes=step_minutes
            )
            day_rows.append(DayOutlook(
                date=day, slot_count=len(slots), slots=tuple(slots)
            ))
            total += len(slots)
        results.append(StaffOutlook(
            staff_member=member, days=tuple(day_rows), total_slots=total
        ))
    return results


#: Aliases matching common caller phrasing.
staff_availability_outlook = availability_outlook
outlook = availability_outlook
