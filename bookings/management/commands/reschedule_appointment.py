"""Reschedule one appointment from the operator CLI (phone / walk-in).

Usage:
    python manage.py reschedule_appointment --appointment-id ID
        --new-start ISO-8601 [--new-end ISO-8601]
        [--new-staff-member-id ID] [--salon-id ID] [--dry-run]

Thin wrapper around
:func:`bookings.lifecycle.reschedule_appointment`: the
appointment is resolved by id (scoped to the salon via both
its client and its staff member when ``--salon-id`` is given,
the bookings salon-scoping convention) and the new times are
passed to the service verbatim -- its reschedulable-status and
rostered-availability refusals stay the single source of
truth and surface here as ``CommandError``. Unlike the
online channel's ``reschedule_booking`` command, this one
calls the lifecycle service directly and does NOT apply the
staff member's online-booking toggle: a phone or walk-in
booking with a non-online stylist can still be moved from
the CLI. ``--new-end`` omitted preserves the original
duration, per the service. With ``--new-staff-member-id``
the new member is resolved by id in the appointment's salon
(an unknown or out-of-salon id is a ``CommandError``) and
passed to the service as its ``new_staff_member`` argument,
which checks the member is active, in the same salon, and
bookable at the new slot; both the real and dry-run outputs
name the from -> to staff change.

With ``--dry-run`` nothing is written: the preview runs the
service layer's read-only ``validate_reschedule_appointment``
helper, which applies the service's own validation without
calling the writer, and prints the move that WOULD apply.
(No transaction rollback is relied on -- on NEDB a
rolled-back transaction does not undo writes.)
Invalid input -- unknown salon/appointment, appointment
outside the salon, unparseable datetime, or a service
``ValidationError`` -- raises ``CommandError``, nothing
written. Backend only -- no views, templates, or UI.
"""
import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from bookings.lifecycle import (
    reschedule_appointment,
    validate_reschedule_appointment,
)
from bookings.models import Appointment
from saloncore.models import Salon
from team.models import StaffMember


def _parse_datetime(value, label):
    if value is None or isinstance(value, datetime.datetime):
        return value
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected ISO-8601 datetime."
        ) from exc


def _resolve(appointment_id, salon_id):
    salon = None
    if salon_id is not None:
        try:
            salon = Salon.objects.get(pk=salon_id)
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {salon_id}.") from None
    qs = Appointment.objects.all()
    if salon is not None:
        qs = qs.filter(client__salon=salon, staff_member__salon=salon)
    try:
        return qs.get(pk=appointment_id)
    except Appointment.DoesNotExist:
        suffix = f" in salon {salon.pk}" if salon is not None else ""
        raise CommandError(
            f"No appointment with id {appointment_id}{suffix}.") from None


def _resolve_new_staff_member(appointment, staff_member_id):
    if staff_member_id is None:
        return None
    salon = appointment.staff_member.salon
    try:
        return StaffMember.objects.filter(salon=salon).get(
            pk=staff_member_id)
    except StaffMember.DoesNotExist:
        raise CommandError(
            f"No staff member with id {staff_member_id} "
            f"in salon {salon.pk}.") from None


class Command(BaseCommand):
    help = ("Reschedule one appointment (phone / walk-in; "
            "online toggle not enforced).")

    def add_arguments(self, parser):
        parser.add_argument("--appointment-id", required=True, type=int,
                            help="Id of the appointment to move.")
        parser.add_argument("--salon-id", type=int, default=None,
                            help="Optional salon the appointment must belong to.")
        parser.add_argument("--new-start", "--start", dest="new_start",
                            required=True,
                            help="New start, ISO-8601 datetime.")
        parser.add_argument("--new-end", "--end", dest="new_end", default=None,
                            help="New end, ISO-8601 (default: preserve duration).")
        parser.add_argument("--new-staff-member-id", type=int, default=None,
                            help="Optional id of the staff member to move "
                                 "the appointment to.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Preview only: validate, print the move, write nothing.")

    def handle(self, *args, **options):
        appointment = _resolve(options.get("appointment_id"),
                               options.get("salon_id"))
        new_staff_member = _resolve_new_staff_member(
            appointment, options.get("new_staff_member_id"))
        new_start = _parse_datetime(
            options.get("new_start") or options.get("start"), "new-start")
        if new_start is None:
            raise CommandError("Provide --new-start.")
        new_end = _parse_datetime(
            options.get("new_end") or options.get("end"), "new-end")
        old_start, old_end = appointment.start, appointment.end
        staff_note = ""
        if new_staff_member is not None:
            staff_note = (
                f", staff {appointment.staff_member.pk} -> "
                f"{new_staff_member.pk}")
        if options.get("dry_run"):
            try:
                preview_end, _staff = validate_reschedule_appointment(
                    appointment, new_start, new_end,
                    new_staff_member=new_staff_member)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would reschedule appointment {appointment.pk}: "
                f"{old_start.isoformat()} -> {new_start.isoformat()}, "
                f"end {old_end.isoformat()} -> {preview_end.isoformat()}"
                f"{staff_note} "
                f"-- no appointment moved.")
            return
        try:
            moved = reschedule_appointment(
                appointment, new_start, new_end,
                new_staff_member=new_staff_member)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Rescheduled appointment {moved.pk}: "
            f"{old_start.isoformat()} -> {moved.start.isoformat()}, "
            f"end {moved.end.isoformat()}{staff_note}.")
