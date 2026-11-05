"""Export a salon's stock adjustments as CSV or JSON.

Usage:
    python manage.py export_adjust --salon-id ID
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--product-id ID] [--output PATH] [--format json|csv]

Backend only — no views, templates, or UI. This command is a thin
wrapper around
:mod:`catalog.adjust_export`: it resolves the salon by id, parses
the optional dates, delegates to that service verbatim (with the
same optional ``start`` / ``end``), and writes the result to
``--output`` when given, otherwise to stdout. For ``--format csv``
(the default) it writes
:func:`catalog.adjust_export.export_stock_adjustments_csv`'s CSV
string as-is, so the historical CSV output is byte-identical; for
``--format json`` it serializes the dict rows from
:func:`catalog.adjust_export.export_stock_adjustments` — the same
rows the CSV is built from — as JSON. It adds no fields, filtering,
or export logic of its own, so the command output and the service
output can never disagree — one source of truth.

Range semantics are the service's own: start-inclusive,
end-exclusive after normalisation, so a date end covers the whole
end day; either bound may be omitted (unbounded).

The optional ``--product-id`` is resolved to its ``Product`` in
the salon and passed to the service as its ``product`` filter;
an id that is unknown — or belongs to another salon — raises
``CommandError``. Omitted, the export is the previous salon-wide
output verbatim.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from catalog.adjust_export import (
    export_stock_adjustments,
    export_stock_adjustments_csv,
)
from catalog.models import Product
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _resolve_product(value, salon):
    if value is None:
        return None
    # A Product instance (via call_command kwargs) resolves by pk.
    pk = getattr(value, "pk", value)
    try:
        pk = int(pk)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid product {value!r}; expected an id."
        ) from exc
    try:
        return Product.objects.get(pk=pk, salon=salon)
    except (Product.DoesNotExist, TypeError, ValueError) as exc:
        raise CommandError(
            f"No product with id {pk}."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's stock adjustments as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stock adjustments to export.",
        )
        parser.add_argument(
            "--start-date", "--start", dest="start_date",
            type=_parse_date, default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--end-date", "--end", dest="end_date",
            type=_parse_date, default=None,
            help="Last day of the range, YYYY-MM-DD (the whole day "
                 "is included; default: unbounded).",
        )
        parser.add_argument(
            "--product-id", dest="product_id",
            type=int, default=None,
            help="Id of the product to scope to (default: "
                 "every product in the salon).",
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
        product_raw = options.get("product_id")
        if product_raw is None:
            product_raw = options.get("product")
        product = _resolve_product(product_raw, salon)
        try:
            if fmt == "json":
                records = export_stock_adjustments(
                    salon, start=options["start_date"],
                    end=options["end_date"], product=product)
                text = json.dumps(records, indent=2) + "\n"
            else:
                text = export_stock_adjustments_csv(
                    salon, start=options["start_date"],
                    end=options["end_date"], product=product)
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
