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
* :func:`reschedule_online_booking` delegates to
  ``bookings.lifecycle.reschedule_appointment``, which enforces
  reschedulable status and rostered availability (excluding the
  appointment itself) at write time. The toggle is checked here
  first — lifecycle reschedule has no online flag — so a staff
  member whose toggle has been turned off since booking cannot
  be moved through online booking.
* :func:`cancel_online_booking` delegates to
  ``bookings.lifecycle.cancel_appointment``, which enforces
  cancellable status (booked/confirmed only) via the lifecycle
  transition table. Cancelling is idempotent here: an already-
  cancelled appointment is returned unchanged instead of raising,
  while any other non-cancellable status (e.g. completed, from
  any channel) is rejected by the lifecycle delegate. No toggle
  check: a client must be able to cancel even if the staff
  member's online-booking toggle has since been turned off.
"""
from django.core.exceptions import ValidationError

from bookings.availability import available_slots
from bookings.lifecycle import (
    cancel_appointment,
    create_appointment,
    reschedule_appointment,
)
from bookings.models import Appointment


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


def reschedule_online_booking(appointment, new_start, new_end=None):
    """Move an existing online-booked appointment to a new start time.

    Rejects the move with ``ValidationError`` (leaving the
    appointment unchanged) when the appointment's staff member's
    online-booking toggle is OFF; otherwise delegates to
    ``bookings.lifecycle.reschedule_appointment``, so
    reschedulable-status and rostered-availability rules (the new
    slot must fit rostered, unoccupied time, excluding this
    appointment itself) are enforced by that one service.
    ``new_end`` defaults there to ``new_start`` plus the
    appointment's original duration.
    """
    if not appointment.staff_member.online_bookable:
        raise ValidationError(
            "This staff member is not bookable online."
        )
    return reschedule_appointment(appointment, new_start, new_end)


def cancel_online_booking(appointment):
    """Cancel an appointment through online booking, idempotently.

    If ``appointment`` is already cancelled, return it unchanged
    (no error, no second transition) so a repeated cancel — a
    double tap, a retried request — yields the same result.
    Otherwise delegate to
    ``bookings.lifecycle.cancel_appointment``, so only
    booked/confirmed appointments can be cancelled and every
    other status (arrived, in service, completed, no-show) raises
    ``ValidationError`` — including a completed appointment
    however it was booked. The row is kept; the slot is freed
    because availability already excludes cancelled appointments.
    """
    if appointment.status == Appointment.Status.CANCELLED:
        return appointment
    return cancel_appointment(appointment)
