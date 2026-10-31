"""Discrete bookable start times for online booking, for one stylist.

Backend only — no views, templates, or branding. This module turns
the free intervals computed by the single availability source of
truth, :func:`bookings.availability.available_slots`, into concrete
start times a client can pick:

* Roster availability and existing appointments are NOT re-derived
  here. The delegate already starts from the staff member's active
  ``RosterPattern`` windows for the weekday and subtracts the day's
  non-cancelled ``Appointment``s (cancelled appointments free their
  slot, as everywhere else in the codebase).
* The per-staff online-booking toggle is enforced twice on purpose:
  a toggle-off (or inactive) staff member short-circuits to ``[]``
  here, and the delegate is also called with ``online_only=True``
  so a toggle-off member could not appear even if that check were
  bypassed.
* Start times step every :data:`SLOT_STEP_MINUTES` minutes from the
  start of each free interval. A start is offered only when the
  whole service fits inside the interval:
  ``start + service_duration <= interval.end``. Stepping restarts
  at each interval's start, so a start right after an appointment
  ends is offered even when it is off the previous interval's grid.
"""
from datetime import datetime, timedelta

from bookings.availability import available_slots as _availability_slots

SLOT_STEP_MINUTES = 15


def _duration_timedelta(service_duration):
    """Normalise ``service_duration`` to a positive ``timedelta``.

    Accepts an ``int``/``float`` number of minutes, a
    ``timedelta``, or a service-like object exposing
    ``total_minutes`` (e.g. ``saloncore.Service``).
    """
    if isinstance(service_duration, timedelta):
        duration = service_duration
    elif hasattr(service_duration, "total_minutes"):
        duration = timedelta(minutes=service_duration.total_minutes)
    elif isinstance(service_duration, (int, float)):
        duration = timedelta(minutes=service_duration)
    else:
        raise TypeError(
            "service_duration must be minutes, a timedelta, or an "
            "object with total_minutes"
        )
    if duration <= timedelta(0):
        raise ValueError("service_duration must be positive")
    return duration


def available_slots(staff, date, service_duration, *, step_minutes=SLOT_STEP_MINUTES):
    """Bookable start times for ``staff`` on ``date``.

    Args:
        staff: a ``team.StaffMember``. If they are inactive or
            their online-booking toggle (``online_bookable``) is
            OFF, no times are bookable online and ``[]`` is
            returned.
        date: a ``datetime.date`` (a datetime is accepted and
            reduced to its date by the availability delegate, in
            the salon timezone).
        service_duration: length of the service to fit — minutes
            (``int``/``float``), a ``timedelta``, or a service-like
            object with ``total_minutes``.
        step_minutes: grid spacing for candidate starts, in minutes
            (keyword-only, default :data:`SLOT_STEP_MINUTES`).

    Returns:
        Chronologically ordered ``list`` of aware ``datetime``
        start times (in the salon timezone, as produced by the
        availability delegate). Empty when the staff member is not
        bookable online, is unrostered that weekday, or no free
        interval is long enough for the service.
    """
    if staff is None or not getattr(staff, "active", False):
        return []
    if not getattr(staff, "online_bookable", False):
        return []
    duration = _duration_timedelta(service_duration)
    if step_minutes <= 0:
        raise ValueError("step_minutes must be positive")
    step = timedelta(minutes=step_minutes)

    salon = getattr(staff, "salon", None)
    if salon is None:
        return []

    starts = []
    for availability in _availability_slots(salon, date, online_only=True):
        if availability.staff_member_id != staff.pk:
            continue
        for interval in availability.intervals:
            start = interval.start
            while start + duration <= interval.end:
                starts.append(start)
                start += step
    starts.sort()
    return starts


# Readable alias for call sites that want start times, not intervals.
bookable_start_times = available_slots

__all__ = ["SLOT_STEP_MINUTES", "available_slots", "bookable_start_times"]
