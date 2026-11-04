"""Export one product's stock history as CSV via the history export service.

Usage:
    python manage.py export_stock_history --salon-id ID
        [--product-id PRODUCT_ID]
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--kind KIND]
        [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around
:func:`catalog.history_export.export_stock_history_csv`:
it resolves the salon by id, delegates to that service verbatim
(with the same optional ``product``, the same optional
``start`` / ``end`` window, and the same optional ``kind``
filter), and writes the returned CSV
to ``--output`` when given, otherwise to stdout. It adds no fields,
filtering, or export logic of its own, so the command output and
the service output can never disagree — one source of truth.

Kind semantics are the service's own: ``--kind`` narrows the
export to movements whose stored kind exactly matches it and
composes with the product and the window; without ``--kind``
the command exports every kind, exactly as before.

Window semantics are the service's own: start-inclusive,
end-exclusive after normalisation, so a date end covers the whole
end day; either bound may be omitted (unbounded, the previous
output verbatim).

Product semantics are the service's own: ``--product-id`` names a
product of this salon by id (the service also accepts a saved
Product instance from programmatic callers); a foreign or unknown
product raises the service's ``ValueError``, surfaced here as
``CommandError``. With no product at all the service requires one,
which likewise surfaces as ``CommandError``.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from catalog.history_export import export_stock_history_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one product's stock history as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stock history to export.",
        )
        parser.add_argument(
            "--product-id", "--product", dest="product_id",
            default=None, type=int,
            help="ID of the product of this salon whose stock "
                 "history to export (default: none, which the "
                 "service rejects as requiring a product).",
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
            "--kind", dest="kind", default=None,
            help="Movement kind value to filter by (default: "
                 "all kinds).",
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
        # Programmatic callers may pass product= a Product/id instead.
        product = options.get("product_id")
        if product is None and options.get("product") is not None:
            product = options["product"]
        start = options.get("start_date")
        if start is None:
            start = options.get("start")
        end = options.get("end_date")
        if end is None:
            end = options.get("end")
        try:
            text = export_stock_history_csv(
                salon, product, start=start, end=end,
                kind=options.get("kind"))
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
