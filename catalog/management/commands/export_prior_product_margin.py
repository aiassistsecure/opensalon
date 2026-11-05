"""Export a salon's prior-period product margin comparison as CSV or JSON.

Usage: python manage.py export_prior_product_margin
    --salon-id ID --start-date YYYY-MM-DD --end-date YYYY-MM-DD
    [--format json|csv] [--output PATH]

Thin wrapper around :mod:`catalog.prior_product_sales_export`:
salon resolved by id, dates parsed and passed verbatim (``start``
/ ``end`` are the current window's inclusive bounds; the prior
window is the equal-length window immediately before it). For
``--format csv`` (the default) it writes
:func:`catalog.prior_product_sales_export.export_prior_product_margin_csv`'s
CSV string as-is, so the historical CSV output is byte-identical;
for ``--format json`` it serialises the same dict rows from
:func:`catalog.prior_product_sales_export.export_prior_product_margin`
-- the same rows the CSV is built from -- as JSON via
``DjangoJSONEncoder``. Output is written to ``--output`` or
stdout. Both dates are required; unknown salon, unparseable /
missing date, unknown format, or a service error (e.g. reversed
range) raises ``CommandError``.
Founding rule (Exit Principle): anything a salon can enter, it
can fully export.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from catalog.prior_product_sales_export import (
    export_prior_product_margin,
    export_prior_product_margin_csv,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc


class Command(BaseCommand):
    help = ("Export a salon's prior-period product margin comparison "
            "as CSV or JSON.")

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", required=True, type=int,
                            help="ID of the salon to export.")
        parser.add_argument(
            "--start-date", "--start", dest="start_date", default=None,
            help="First day of the current window, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--end-date", "--end", dest="end_date", default=None,
            help="Last day of the current window, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None,
                            help="Path of the export file to write "
                                 "(default: stdout).")

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
        start = _parse_date(options["start_date"])
        end = _parse_date(options["end_date"])
        try:
            if fmt == "json":
                records = export_prior_product_margin(
                    salon, start_date=start, end_date=end)
                text = json.dumps(
                    records, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_prior_product_margin_csv(
                    salon, start_date=start, end_date=end)
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
