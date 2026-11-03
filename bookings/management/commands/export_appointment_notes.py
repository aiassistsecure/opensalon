"""Export a salon's appointment-only notes verbatim as CSV.

Usage:
    python manage.py export_appointment_notes --salon-id ID
        [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD]
        [--output PATH]

Thin wrapper around
``bookings.note_export.export_appointment_notes_csv`` -- that
service is the one source of truth for the appointment-note
export shape; this command only resolves the salon, parses the
dates, delegates verbatim, and routes the CSV it returns to the
``--output`` file when given or to stdout otherwise. It never
reimplements serialization or querying. Only appointment-only
notes are exported; persistent client record notes live in the
clients app and never appear. With no dates, every appointment
note for the salon is exported.

Backend only: no views, templates, or UI. No provider concepts.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.note_export import export_appointment_notes_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value, label):
    if value is None or isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's appointment-only notes verbatim as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="ID of the salon whose appointment notes to export.",
        )
        parser.add_argument(
            "--date-from", "--from-date", "--start-date",
            dest="date_from", type=_parse_date, default=None,
            help="Inclusive first day (on note created_at), YYYY-MM-DD.",
        )
        parser.add_argument(
            "--date-to", "--to-date", "--end-date",
            dest="date_to", type=_parse_date, default=None,
            help="Inclusive last day (on note created_at), YYYY-MM-DD "
                 "(default: the service's own default).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None
        date_from = _coerce_date(options.get("date_from"), "date_from")
        date_to = _coerce_date(options.get("date_to"), "date_to")
        try:
            text = export_appointment_notes_csv(salon, date_from, date_to)
        except Exception as exc:
            raise CommandError(
                f"Appointment notes export failed: {exc}") from exc
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
