"""Export a salon's low-stock report as CSV or JSON via the service.

Usage:
    python manage.py export_low_stock --salon-id ID
        [--threshold N] [--format json|csv] [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :mod:`catalog.low_stock_export`: it resolves the
salon by id, delegates to that service verbatim (with the same
optional ``threshold``), and writes the result to ``--output``
when given, otherwise to stdout. For ``--format csv`` (the
default) it writes
:func:`catalog.low_stock_export.export_low_stock_csv`'s CSV
string as-is, so the historical CSV output is byte-identical;
for ``--format json`` it serializes the dict rows from
:func:`catalog.low_stock_export.export_low_stock` — the same
rows the CSV is built from — as JSON. It adds no fields,
filtering, or formatting of its own, so the command output and
the service output can never disagree — one source of truth.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from catalog.low_stock_export import export_low_stock, export_low_stock_csv
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's low-stock report as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose low-stock report to export.",
        )
        parser.add_argument(
            "--threshold", default=None, type=int,
            help="Only products at or below this on-hand quantity "
                 "(default: the service's default threshold).",
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
                records = export_low_stock(
                    salon, threshold=options["threshold"])
                text = json.dumps(records, indent=2) + "\n"
            else:
                text = export_low_stock_csv(
                    salon, threshold=options["threshold"])
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
