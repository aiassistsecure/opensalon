"""Export a salon's products as CSV or JSON via the catalog export service.

Usage:
    python manage.py export_products --salon-id ID
        [--include-inactive] [--product-type TYPE]
        [--format json|csv] [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :mod:`catalog.export`: it resolves the salon by id,
delegates to that service verbatim (with the same
``include_inactive`` and ``product_type``), and writes the result
to ``--output`` when given, otherwise to stdout. For
``--format csv`` (the default) it writes
:func:`catalog.export.export_products_csv`'s CSV string as-is, so
the historical CSV output is byte-identical; for
``--format json`` it serializes the dict rows from
:func:`catalog.export.export_products` — the same rows the CSV is
built from — as JSON. It adds no fields, filtering, or formatting
of its own, so the command output and the service output can never
disagree — one source of truth.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from catalog.export import export_products, export_products_csv
from saloncore.models import Salon

_FORMATS = ("json", "csv")


class Command(BaseCommand):
    help = "Export a salon's products as CSV or JSON (sku/barcode included)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose products to export.",
        )
        parser.add_argument(
            "--include-inactive", action="store_true", default=False,
            help="Include inactive products (default: excluded).",
        )
        parser.add_argument(
            "--product-type", default=None,
            help="Only export products whose stored product_type "
                 "equals this value exactly (default: all types).",
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
        if fmt == "json":
            records = export_products(
                salon, include_inactive=options["include_inactive"],
                product_type=options["product_type"])
            text = json.dumps(records, indent=2) + "\n"
        else:
            text = export_products_csv(
                salon, include_inactive=options["include_inactive"],
                product_type=options["product_type"])
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
