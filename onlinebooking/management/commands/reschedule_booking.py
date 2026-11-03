"""Reschedule one online-booked appointment.

Usage:
    python manage.py reschedule_booking --appointment-id ID
        --new-start ISO-8601 [--new-end ISO-8601]
        [--salon-id ID] [--dry-run]

Thin wrapper around
:func:`onlinebooking.services.reschedule_online_booking` (which
delegates to ``bookings.lifecycle`` guards): the appointment
is resolved by id (scoped to the salon via both its client and
its staff member when ``--salon-id`` is given, the bookings
salon-scoping convention) and the new times are passed to the
service verbatim -- its toggle, reschedulable-status, and
rostered-availability refusals stay the single source of truth
and surface here as ``CommandError``. ``--new-end`` omitted
preserves the original duration, per the service.

With ``--dry-run`` nothing is written: the service runs inside
a transaction that is rolled back, so the preview applies the
service's own validation and prints the move that WOULD apply.
Invalid input -- unknown salon/appointment, appointment outside
the salon, unparseable datetime, or a service
``ValidationError`` -- raises ``CommandError``, nothing written.
Backend only -- no views, templates, or UI.
"""
import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bookings.models import Appointment
from onlinebooking.services import reschedule_online_booking
from saloncore.models import Salon


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


class Command(BaseCommand):
    help = "Reschedule one online-booked appointment."

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
        parser.add_argument("--dry-run", action="store_true",
                            help="Preview only: validate, print the move, write nothing.")

    def handle(self, *args, **options):
        appointment = _resolve(options.get("appointment_id"),
                               options.get("salon_id"))
        new_start = _parse_datetime(
            options.get("new_start") or options.get("start"), "new-start")
        if new_start is None:
            raise CommandError("Provide --new-start.")
        new_end = _parse_datetime(
            options.get("new_end") or options.get("end"), "new-end")
        old_start, old_end = appointment.start, appointment.end
        if options.get("dry_run"):
            try:
                with transaction.atomic():
                    moved = reschedule_online_booking(
                        appointment, new_start, new_end)
                    preview = (moved.start, moved.end)
                    transaction.set_rollback(True)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would reschedule appointment {appointment.pk}: "
                f"{old_start.isoformat()} -> {preview[0].isoformat()}, "
                f"end {old_end.isoformat()} -> {preview[1].isoformat()} "
                f"-- no appointment moved.")
            return
        try:
            moved = reschedule_online_booking(appointment, new_start, new_end)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Rescheduled appointment {moved.pk}: "
            f"{old_start.isoformat()} -> {moved.start.isoformat()}, "
            f"end {moved.end.isoformat()}.")
