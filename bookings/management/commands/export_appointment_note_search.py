"""Export a salon's appointment-note search results as CSV.

Usage:
    python manage.py export_appointment_note_search --salon-id ID
        [--query TEXT] [--output PATH]

Thin wrapper around
``bookings.note_search_export.export_appointment_note_search_results_csv``
-- that service is the one source of truth; this command only
resolves the salon, delegates verbatim, and routes the CSV to
``--output`` or stdout. Only appointment-only notes are exported;
client record notes never appear. Backend only; read-only.
"""
from django.core.management.base import BaseCommand, CommandError

from bookings.note_search_export import (
    export_appointment_note_search_results_csv,
)
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export a salon's appointment-note search results as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="ID of the salon whose notes to search.")
        parser.add_argument("--query", dest="query", default=None,
                            help="Search text for note body/author "
                                 "(default: all appointment notes).")
        parser.add_argument("--output", default=None,
                            help="CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None
        try:
            text = export_appointment_note_search_results_csv(
                salon, query=options.get("query"))
        except Exception as exc:
            raise CommandError(
                f"Appointment note search export failed: {exc}") from exc
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
