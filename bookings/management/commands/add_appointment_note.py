"""Add an appointment-only note to one appointment.

Usage:
    python manage.py add_appointment_note --appointment-id ID
        --text TEXT [--author NAME] [--salon-id ID] [--dry-run]

With ``--dry-run`` nothing is written: the command runs the
service inside a transaction it rolls back, so the preview
applies the service's own validation and prints the note that
WOULD be created (its appointment, body, and author).

Thin wrapper around :func:`bookings.notes.add_note`: the
appointment is resolved by id (scoped to the salon via both
its client and its staff member when ``--salon-id`` is given,
the bookings salon-scoping convention), and the text/author
are passed to the service verbatim -- its refusal of empty
text stays the single source of truth and surfaces here as
``CommandError``. This command adds no note logic of its own,
so command and service can never disagree. The note is
appointment-only; no persistent client record note is created.

Invalid input -- an unknown salon, an unknown appointment, an
appointment outside the given salon, or a service
``ValidationError`` -- raises ``CommandError`` and nothing is
written. Backend only -- no views, templates, or UI.
"""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bookings.models import Appointment
from bookings.notes import add_note
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Add an appointment-only note to one appointment."

    def add_arguments(self, parser):
        parser.add_argument(
            "--appointment-id", required=True, type=int,
            help="Id of the appointment to add the note to.")
        parser.add_argument(
            "--salon-id", type=int, default=None,
            help="Optional id of the salon the appointment must "
                 "belong to (via both its client and its staff "
                 "member).")
        parser.add_argument(
            "--text", "--body", "--note", dest="text",
            required=True,
            help="Text (body) of the appointment note.")
        parser.add_argument(
            "--author", "--author-name", dest="author", default="",
            help="Optional author name stored on the note.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: run the service inside a "
                 "transaction that is rolled back, print the "
                 "note that would be created, and write nothing.")

    def handle(self, *args, **options):
        appointment_id = options.get("appointment_id")
        if appointment_id is None:
            raise CommandError("Provide --appointment-id.")
        # ``body``/``note`` are aliases if supplied via
        # call_command kwargs.
        text = (options.get("text") or options.get("body")
                or options.get("note"))
        if text is None:
            raise CommandError("Provide --text.")
        author = (options.get("author")
                  or options.get("author_name") or "")
        salon_id = options.get("salon_id")
        salon = None
        if salon_id is not None:
            try:
                salon = Salon.objects.get(pk=salon_id)
            except Salon.DoesNotExist:
                raise CommandError(
                    f"No salon with id {salon_id}.") from None
        qs = Appointment.objects.all()
        if salon is not None:
            qs = qs.filter(client__salon=salon,
                           staff_member__salon=salon)
        try:
            appointment = qs.get(pk=appointment_id)
        except Appointment.DoesNotExist:
            if salon is not None:
                raise CommandError(
                    f"No appointment with id {appointment_id} "
                    f"in salon {salon.pk}.") from None
            raise CommandError(
                f"No appointment with id {appointment_id}.") from None
        if options.get("dry_run"):
            try:
                with transaction.atomic():
                    note = add_note(appointment, text, author=author)
                    preview = (note.body, note.author_name)
                    transaction.set_rollback(True)
            except ValidationError as exc:
                raise CommandError(
                    "; ".join(exc.messages)) from exc
            body, author_name = preview
            self.stdout.write(
                f"Dry run: would create appointment note for "
                f"appointment {appointment.pk}: body={body!r} "
                f"author={author_name!r} -- no note written.")
            return
        try:
            note = add_note(appointment, text, author=author)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(
            f"Added note {note.pk} to appointment "
            f"{appointment.pk}: {note.body!r}")
