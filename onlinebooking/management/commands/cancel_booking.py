"""Cancel one appointment through online booking.

Usage:
    python manage.py cancel_booking --appointment-id ID
        [--salon-id ID] [--dry-run]

Thin wrapper around
:func:`onlinebooking.services.cancel_online_booking` (which
delegates to ``bookings.lifecycle`` guards): the appointment
is resolved by id (scoped to the salon via both its client and
its staff member when ``--salon-id`` is given, the bookings
salon-scoping convention) and passed to the service verbatim --
its cancellable-status refusal stays the single source of
truth and surfaces here as ``CommandError``. Cancellation is
idempotent per the service: an already-cancelled appointment
is reported unchanged, not an error. The row is kept.

With ``--dry-run`` nothing is written: the preview runs the
service layer's read-only ``validate_cancel_online_booking``
helper, which applies the service's own validation without
calling the writer, and prints the cancellation that WOULD
apply. (No transaction rollback is relied on -- on NEDB a
rolled-back transaction does not undo writes.) Invalid input
-- unknown salon/appointment, appointment outside the salon,
or a service ``ValidationError`` -- raises ``CommandError``,
nothing written.
Backend only -- no views, templates, or UI.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from bookings.models import Appointment
from onlinebooking.services import (
    cancel_online_booking,
    validate_cancel_online_booking,
)
from saloncore.models import Salon


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


class Command(BaseCommand):
    help = "Cancel one appointment through online booking."

    def add_arguments(self, parser):
        parser.add_argument("--appointment-id", required=True, type=int,
                            help="Id of the appointment to cancel.")
        parser.add_argument("--salon-id", type=int, default=None,
                            help="Optional salon the appointment must belong to.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Preview only: validate, print the cancellation, write nothing.")

    def handle(self, *args, **options):
        appointment = _resolve(options.get("appointment_id"),
                               options.get("salon_id"))
        old_status = appointment.status
        if options.get("dry_run"):
            try:
                preview_status = validate_cancel_online_booking(appointment)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would cancel appointment {appointment.pk}: "
                f"status {old_status} -> {preview_status} "
                f"-- no appointment cancelled.")
            return
        try:
            cancelled = cancel_online_booking(appointment)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Cancelled appointment {cancelled.pk}: "
            f"status {old_status} -> {cancelled.status}.")
