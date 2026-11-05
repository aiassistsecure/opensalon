"""Export a salon's appointment-note search results as CSV or JSON.

Usage:
    python manage.py export_appointment_note_search --salon-id ID
        [--query TEXT] [--format json|csv] [--output PATH]

Thin wrapper around
``bookings.note_search_export`` -- that service is the one source
of truth; this command only resolves the salon, delegates
verbatim, and routes the result to ``--output`` or stdout. For
``--format csv`` (the default) it writes
:func:`bookings.note_search_export.export_appointment_note_search_results_csv`'s
CSV string, exactly as before, byte-identical; for
``--format json`` it serialises the SAME dict rows from
:func:`bookings.note_search_export.export_appointment_note_search_results`
as JSON via ``DjangoJSONEncoder``, so the two formats can never
disagree. Only appointment-only notes are exported; client record
notes never appear. Backend only; read-only.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from bookings.note_search_export import (
    export_appointment_note_search_results,
    export_appointment_note_search_results_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's appointment-note search results as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="ID of the salon whose notes to search.")
        parser.add_argument("--query", dest="query", default=None,
                            help="Search text for note body/author "
                                 "(default: all appointment notes).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument("--output", default=None,
                            help="CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None
        try:
            if fmt == "json":
                rows = export_appointment_note_search_results(
                    salon, query=options.get("query"))
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
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
