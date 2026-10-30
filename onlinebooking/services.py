"""Online booking service: the public-booking write/read path.

Backend only — no views, templates, or salon branding (branding is
a UI-track concern). This module is a thin gate over the existing
services; it duplicates no availability or lifecycle logic:

* :func:`bookable_slots` delegates to
  ``bookings.availability.available_slots(..., online_only=True)``,
  so only rostered time (minus existing appointments, long enough
  for the service) is offered, and only for active staff whose
  per-staff online-booking toggle (``StaffMember.online_bookable``)
  is ON. Toggle-off staff never appear; unrostered time is never
  offered.
* :func:`create_online_booking` delegates to
  ``bookings.lifecycle.create_appointment(..., online=True)``,
  which re-checks the toggle and rostered availability at write
  time. The toggle is also checked here first so a direct call
  fails with a clear online-booking message even before the
  lifecycle checks run.
"""
from django.core.exceptions import ValidationError

from bookings.availability import available_slots
from bookings.lifecycle import create_appointment


def bookable_slots(salon, service, day):
    """Bookable free intervals for ``salon`` on ``day`` for ``service``.

    Args:
        salon: ``saloncore.Salon`` instance.
        service: ``saloncore.Service`` to book; only intervals at
            least ``service.total_minutes`` long are returned.
        day: a ``datetime.date`` (a datetime is reduced to its date
            in the salon timezone, per ``available_slots``).

    Returns:
        list of ``bookings.availability.StaffAvailability`` for
        online-bookable staff only, as returned by
        ``available_slots(..., online_only=True)``.
    """
    return available_slots(salon, day, service=service, online_only=True)


def create_online_booking(*, client, staff_member, service, start,
                          end=None, note="", note_author=""):
    """Create an appointment through online booking.

    Rejects staff whose online-booking toggle is OFF with
    ``ValidationError`` (creating nothing); otherwise delegates to
    ``bookings.lifecycle.create_appointment`` with ``online=True``,
    so rostered-availability, cross-salon, active, and overlap
    rules are enforced by that one service. ``end`` defaults there
    to ``start`` plus the service's total minutes, and a non-empty
    ``note`` becomes an appointment-only note.
    """
    if not staff_member.online_bookable:
        raise ValidationError(
            "This staff member is not bookable online."
        )
    return create_appointment(
        client=client, staff_member=staff_member, service=service,
        start=start, end=end, note=note, note_author=note_author,
        online=True,
    )
