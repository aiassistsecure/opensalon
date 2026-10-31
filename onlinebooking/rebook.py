"""Rebook (book again) from a past appointment.

Backend only — no views, templates, or branding.

Rebooking creates a NEW ``bookings.Appointment`` for the same
client, staff member, and service as a source appointment, at a
new start time. It never moves or mutates the source row.

The write goes through the existing online-booking creation path
(:func:`onlinebooking.services.create_online_booking`), so every
rule that path enforces applies unchanged and is not re-derived
here:

* the staff member's per-staff online-booking toggle must be ON
  at rebook time (a toggle turned off since the original visit
  refuses the rebook, creating nothing);
* the new slot must fit rostered, unoccupied time for that staff
  member (via ``bookings.lifecycle.create_appointment`` with
  ``online=True``), plus the cross-salon / active checks.

Source rules
------------
* A cancelled source appointment is refused with
  ``ValidationError`` (creating nothing): a cancelled booking is
  not a visit to book again from.
* A source with no service (snapshot-only, ``service is None``)
  is refused with ``ValidationError``: there is no price-book
  service to book again.
* Any other source status (booked, confirmed, completed, etc.)
  may be rebooked; this module does not invent a ``past`` check
  beyond the caller's choice of source — the new booking's own
  availability checks govern the new slot.
"""
from django.core.exceptions import ValidationError

from bookings.models import Appointment
from onlinebooking.services import create_online_booking

__all__ = ["rebook_appointment", "rebook_booking", "book_again"]


def _resolve_source(source):
    """Return the source ``Appointment`` for an instance or id."""
    if isinstance(source, Appointment):
        return source
    try:
        return Appointment.objects.select_related(
            "client", "staff_member", "service"
        ).get(pk=source)
    except (Appointment.DoesNotExist, ValueError, TypeError):
        raise ValidationError("Source appointment does not exist.")


def rebook_appointment(source, new_start, new_end=None, *,
                       note="", note_author=""):
    """Create a new booking copying client/staff/service from ``source``.

    Args:
        source: a ``bookings.Appointment`` instance or its id.
        new_start: aware datetime for the new appointment. ``new_end``
            defaults (in the creation service) to ``new_start`` plus
            the service's total minutes.

    Returns:
        The newly created ``Appointment`` (status booked). The
        source appointment is unchanged.

    Raises:
        ValidationError: source missing, source cancelled, source
            has no service, staff toggle OFF, or the new slot is
            outside rostered availability / overlaps (from the
            delegated creation service).
    """
    appointment = _resolve_source(source)
    if appointment.status == Appointment.Status.CANCELLED:
        raise ValidationError(
            "A cancelled appointment cannot be rebooked."
        )
    if appointment.service is None:
        raise ValidationError(
            "This appointment has no service to rebook."
        )
    return create_online_booking(
        client=appointment.client,
        staff_member=appointment.staff_member,
        service=appointment.service,
        start=new_start,
        end=new_end,
        note=note,
        note_author=note_author,
    )


#: Aliases matching common caller phrasing.
rebook_booking = rebook_appointment
book_again = rebook_appointment
