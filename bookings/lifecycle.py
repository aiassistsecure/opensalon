"""Appointment lifecycle service: create, reschedule, cancel.

Pure service module — no views, no UI. This is the write path that
sits on top of :mod:`bookings.availability`: appointments may only
be created or moved into rostered, unoccupied time, and the check
reuses availability's own merge/subtract helpers and rules
(roster windows for the weekday minus the day's non-cancelled
appointments) rather than re-deriving a second definition of free
time.

Status flow is enforced here, in one place::

    booked    -> confirmed, arrived, cancelled, no_show
    confirmed -> arrived, cancelled, no_show
    arrived   -> in_service
    in_service -> completed
    completed / cancelled / no_show -> (terminal, no transitions)

Rescheduling is only possible from booked/confirmed, and only the
appointment row moves: its ``AppointmentNote`` rows stay attached
to that same appointment, untouched. Notes are appointment-only —
this module never creates a ``clients.ClientNote`` and never
copies a note onto the client record.
"""
from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from bookings.availability import _merge, _subtract, _tz
from bookings.models import Appointment, AppointmentNote
from team.models import RosterPattern

ALLOWED_TRANSITIONS = {
    Appointment.Status.BOOKED: frozenset({
        Appointment.Status.CONFIRMED, Appointment.Status.ARRIVED,
        Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW,
    }),
    Appointment.Status.CONFIRMED: frozenset({
        Appointment.Status.ARRIVED, Appointment.Status.CANCELLED,
        Appointment.Status.NO_SHOW,
    }),
    Appointment.Status.ARRIVED: frozenset({Appointment.Status.IN_SERVICE}),
    Appointment.Status.IN_SERVICE: frozenset({Appointment.Status.COMPLETED}),
    Appointment.Status.COMPLETED: frozenset(),
    Appointment.Status.CANCELLED: frozenset(),
    Appointment.Status.NO_SHOW: frozenset(),
}

RESCHEDULABLE_STATUSES = frozenset({
    Appointment.Status.BOOKED, Appointment.Status.CONFIRMED,
})


def _require_aware(value, field):
    if not isinstance(value, datetime) or timezone.is_naive(value):
        raise ValidationError({field: "Must be a timezone-aware datetime."})


def _resolve_end(start, end, service):
    if end is None:
        end = start + timedelta(minutes=service.total_minutes)
    _require_aware(end, "end")
    if end <= start:
        raise ValidationError({"end": "End must be after start."})
    return end


def _fits_availability(salon, staff_member, start, end, *, exclude_id=None):
    """True when [start, end) fits inside one free interval that day.

    Mirrors ``available_slots`` for a single staff member: roster
    windows for the (salon-local) weekday minus that day's
    non-cancelled appointments, optionally excluding one appointment
    (the one being rescheduled, so it does not block its own move).
    """
    tz = _tz(salon)
    local_day = start.astimezone(tz).date()
    if end.astimezone(tz).date() != local_day:
        return False  # appointments live inside one day-book day
    windows = [
        (datetime.combine(local_day, p.start_time, tzinfo=tz),
         datetime.combine(local_day, p.end_time, tzinfo=tz))
        for p in RosterPattern.objects.filter(
            staff_member=staff_member, weekday=local_day.weekday(), active=True,
        )
    ]
    if not windows:
        return False
    day_start = datetime.combine(local_day, time.min, tzinfo=tz)
    busy_qs = Appointment.objects.filter(
        staff_member=staff_member,
        start__lt=day_start + timedelta(days=1), end__gt=day_start,
    ).exclude(status=Appointment.Status.CANCELLED)
    if exclude_id is not None:
        busy_qs = busy_qs.exclude(pk=exclude_id)
    free = _subtract(_merge(windows), _merge([(a.start, a.end) for a in busy_qs]))
    return any(s <= start and end <= e for s, e in free)


def _check_bookable(salon, staff_member, service, start, end, *,
                    online=False, exclude_id=None):
    if online and not staff_member.online_bookable:
        raise ValidationError(
            "This staff member is not bookable online."
        )
    if not _fits_availability(
        salon, staff_member, start, end, exclude_id=exclude_id,
    ):
        raise ValidationError(
            "Requested time is outside rostered availability or "
            "overlaps another appointment for this staff member."
        )


@transaction.atomic
def create_appointment(*, client, staff_member, service, start, end=None,
                       note="", note_author="", online=False):
    """Create a booked appointment in rostered, free time.

    ``end`` defaults to ``start`` plus the service's total minutes.
    Raises ``ValidationError`` when the client/staff/service belong
    to different salons, staff or service is inactive, the time is
    naive, or the slot is not available (see
    :func:`_fits_availability`; ``online=True`` also enforces the
    staff member's online-booking toggle). A non-empty ``note``
    becomes one appointment-only ``AppointmentNote`` on the new
    appointment — never a client record note.
    """
    _require_aware(start, "start")
    end = _resolve_end(start, end, service)
    salon = staff_member.salon
    if client.salon_id != salon.pk:
        raise ValidationError("Client belongs to a different salon.")
    if service.category.salon_id != salon.pk:
        raise ValidationError("Service belongs to a different salon.")
    if not staff_member.active:
        raise ValidationError("Staff member is not active.")
    if not service.active:
        raise ValidationError("Service is not active.")
    _check_bookable(salon, staff_member, service, start, end, online=online)
    appointment = Appointment.objects.create(
        client=client, staff_member=staff_member, service=service,
        start=start, end=end,
    )
    if note:
        AppointmentNote.objects.create(
            appointment=appointment, body=note, author_name=note_author,
        )
    return appointment


def transition_status(appointment, new_status):
    """Move ``appointment`` to ``new_status`` if the flow allows it."""
    allowed = ALLOWED_TRANSITIONS.get(appointment.status, frozenset())
    if new_status not in allowed:
        raise ValidationError(
            f"Cannot move an appointment from {appointment.status} "
            f"to {new_status}."
        )
    appointment.status = new_status
    appointment.save(update_fields=["status", "updated_at"])
    return appointment


@transaction.atomic
def reschedule_appointment(appointment, new_start, new_end=None, *,
                           new_staff_member=None):
    """Move an appointment to a new time (and optionally staff member).

    Only booked/confirmed appointments can move. When ``new_end``
    is omitted the original duration is preserved. The target slot
    must be available for the (possibly new) staff member,
    excluding this appointment itself. The appointment row is
    updated in place, so its appointment-only notes stay attached
    to it, unchanged, and are never copied to the client record.
    """
    if appointment.status not in RESCHEDULABLE_STATUSES:
        raise ValidationError(
            f"A {appointment.status} appointment cannot be rescheduled."
        )
    _require_aware(new_start, "new_start")
    staff_member = new_staff_member or appointment.staff_member
    duration = appointment.end - appointment.start
    if new_end is None:
        new_end = new_start + duration
    _require_aware(new_end, "new_end")
    if new_end <= new_start:
        raise ValidationError({"new_end": "End must be after start."})
    if not staff_member.active:
        raise ValidationError("Staff member is not active.")
    if staff_member.salon_id != appointment.staff_member.salon_id:
        raise ValidationError("Staff member belongs to a different salon.")
    _check_bookable(
        staff_member.salon, staff_member, appointment.service,
        new_start, new_end, exclude_id=appointment.pk,
    )
    appointment.start = new_start
    appointment.end = new_end
    appointment.staff_member = staff_member
    appointment.save(update_fields=["start", "end", "staff_member", "updated_at"])
    return appointment


def cancel_appointment(appointment):
    """Cancel an appointment, freeing its slot for rebooking.

    Goes through :func:`transition_status`, so only booked/confirmed
    appointments can be cancelled; terminal or in-progress states
    raise ``ValidationError``. The row (and its appointment-only
    notes) is kept — cancelled appointments simply stop occupying
    the book, as availability already excludes them.
    """
    return transition_status(appointment, Appointment.Status.CANCELLED)
