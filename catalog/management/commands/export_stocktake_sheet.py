"""Export a salon's stocktake sheet as CSV via the stocktake sheet export service.

Usage:
    python manage.py export_stocktake_sheet --salon-id ID
        [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around
:func:`catalog.stocktake_sheet_export.export_stocktake_sheet_csv`:
it resolves the salon by id, delegates to that service verbatim,
and writes the returned CSV to ``--output`` when given, otherwise
to stdout. It adds no fields, filtering, or formatting of its
own, so the command output and the service output can never
disagree — one source of truth.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.
"""
from django.core.management.base import BaseCommand, CommandError

from catalog.stocktake_sheet_export import export_stocktake_sheet_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export a salon's stocktake sheet as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stocktake sheet to export.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            text = export_stocktake_sheet_csv(salon)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
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
