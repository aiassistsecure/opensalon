"""Export a salon's stocktake sheet as CSV or JSON via the stocktake sheet export service.

Usage:
    python manage.py export_stocktake_sheet --salon-id ID
        [--format json|csv] [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :mod:`catalog.stocktake_sheet_export`: it resolves
the salon by id and delegates to that service verbatim. For
``--format csv`` (the default) it writes
:func:`catalog.stocktake_sheet_export.export_stocktake_sheet_csv`'s
CSV string as-is, so the historical CSV output is byte-identical;
for ``--format json`` it serializes the dict rows from
:func:`catalog.stocktake_sheet_export.export_stocktake_sheet` —
the same rows the CSV is built from — as JSON. Output goes to
``--output`` when given, otherwise to stdout. It adds no fields,
filtering, or formatting of its own, so the command output and
the service output can never disagree — one source of truth.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from catalog.stocktake_sheet_export import (
    export_stocktake_sheet,
    export_stocktake_sheet_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's stocktake sheet as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stocktake sheet to export.",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            if fmt == "json":
                records = export_stocktake_sheet(salon)
                text = json.dumps(records, indent=2) + "\n"
            else:
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
