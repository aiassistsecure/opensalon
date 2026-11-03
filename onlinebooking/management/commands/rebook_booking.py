"""Rebook (book again) from a past appointment.

Usage:
    python manage.py rebook_booking --appointment-id ID
        --new-start ISO-8601 [--new-end ISO-8601]
        [--salon-id ID] [--note TEXT] [--note-author TEXT]
        [--dry-run]

Thin wrapper around
:func:`onlinebooking.rebook.rebook_appointment`: the source
appointment is resolved by id (scoped to the salon via both
its client and its staff member when ``--salon-id`` is given,
the bookings salon-scoping convention) and the new times are
passed to the service verbatim -- its cancelled-source,
no-service, toggle, and rostered-availability refusals stay
the single source of truth and surface here as
``CommandError``. Rebooking creates a NEW appointment; the
source is never moved or mutated. ``--new-end`` omitted
defaults (in the creation service) to ``--new-start`` plus
the service's total minutes.

With ``--dry-run`` nothing is written: the preview runs the
service layer's read-only ``validate_rebook_appointment``
helper, which applies the service's own validation without
calling the writer, and prints the booking that WOULD be
created. (No transaction rollback is relied on -- on NEDB a
rolled-back transaction does not undo writes.) Invalid input
-- unknown salon/appointment, appointment outside the salon,
unparseable datetime, or a service ``ValidationError`` --
raises ``CommandError``, nothing written.
Backend only -- no views, templates, or UI.
"""
import datetime

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from bookings.models import Appointment
from onlinebooking.rebook import rebook_appointment, validate_rebook_appointment
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
    help = "Rebook (book again) from a past appointment."

    def add_arguments(self, parser):
        parser.add_argument("--appointment-id", required=True, type=int,
                            help="Id of the source appointment to rebook from.")
        parser.add_argument("--salon-id", type=int, default=None,
                            help="Optional salon the appointment must belong to.")
        parser.add_argument("--new-start", "--start", dest="new_start",
                            required=True,
                            help="New start, ISO-8601 datetime.")
        parser.add_argument("--new-end", "--end", dest="new_end", default=None,
                            help="New end, ISO-8601 (default: service duration).")
        parser.add_argument("--note", default="",
                            help="Optional appointment note for the new booking.")
        parser.add_argument("--note-author", default="",
                            help="Optional author for --note.")
        parser.add_argument("--dry-run", action="store_true",
                            help="Preview only: validate, print the booking, write nothing.")

    def handle(self, *args, **options):
        source = _resolve(options.get("appointment_id"),
                          options.get("salon_id"))
        new_start = _parse_datetime(
            options.get("new_start") or options.get("start"), "new-start")
        if new_start is None:
            raise CommandError("Provide --new-start.")
        new_end = _parse_datetime(
            options.get("new_end") or options.get("end"), "new-end")
        note = options.get("note") or ""
        note_author = options.get("note_author") or ""
        if options.get("dry_run"):
            try:
                preview_end = validate_rebook_appointment(
                    source, new_start, new_end,
                    note=note, note_author=note_author)
            except ValidationError as exc:
                raise CommandError("; ".join(exc.messages)) from exc
            self.stdout.write(
                f"Dry run: would rebook appointment {source.pk}: "
                f"new booking at {new_start.isoformat()}, "
                f"end {preview_end.isoformat()}, "
                f"status {Appointment.Status.BOOKED} "
                f"-- no appointment created.")
            return
        try:
            created = rebook_appointment(
                source, new_start, new_end,
                note=note, note_author=note_author)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Rebooked appointment {source.pk}: "
            f"new appointment {created.pk} at {created.start.isoformat()}, "
            f"end {created.end.isoformat()}, status {created.status}.")
