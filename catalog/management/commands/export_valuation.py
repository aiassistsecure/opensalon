"""Export a salon's stock valuation as CSV or JSON.

Usage:
    python manage.py export_valuation --salon-id ID
        [--format json|csv] [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :mod:`catalog.valuation_export`: it resolves the
salon by id; for ``--format csv`` (the default) it writes
:func:`catalog.valuation_export.export_stock_valuation_csv`'s
CSV string as-is, so the historical CSV output is byte-identical;
for ``--format json`` it serialises the same dict rows from
:func:`catalog.valuation_export.export_stock_valuation` — the
same rows the CSV is built from — as JSON via
``DjangoJSONEncoder``. Output is written to ``--output`` when
given, otherwise to stdout. Unknown salon or unknown format
raises ``CommandError``.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from catalog.valuation_export import (
    export_stock_valuation,
    export_stock_valuation_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's stock valuation as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stock valuation to export.",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
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
        if fmt == "json":
            text = json.dumps(
                export_stock_valuation(salon), indent=2,
                cls=DjangoJSONEncoder) + "\n"
        else:
            text = export_stock_valuation_csv(salon)
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
