"""Export a salon's prior (same-weekday) daily-sales report as CSV or JSON.

Usage: python manage.py export_prior_daily_sales --salon-id ID
--date YYYY-MM-DD [--format json|csv] [--output PATH]
Thin wrapper around :mod:`checkout.prior_daily_sales_export`:
for ``--format csv`` (the default) the CSV text from
:func:`checkout.prior_daily_sales_export.export_prior_daily_sales_csv`
is written unchanged; for ``--format json`` the same dict rows
from :func:`checkout.prior_daily_sales_export.export_prior_daily_sales`
are serialised via ``json.dumps(indent=2)``, so the two formats
can never disagree. Output goes to ``--output`` or stdout.
Unknown salon, unparseable/missing date, unknown format, or
service error raises ``CommandError``. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from checkout.prior_daily_sales_export import (
    export_prior_daily_sales, export_prior_daily_sales_csv)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value, label):
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(f"Invalid {label} {value!r}; expected YYYY-MM-DD.") from exc


class Command(BaseCommand):
    help = "Export a salon's prior (same-weekday) daily-sales report as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--date", "--day", "--start-date", dest="date",
                            default=None, help="Day to report, YYYY-MM-DD.")
        parser.add_argument("--format", dest="format", default="csv",
                            choices=_FORMATS,
                            help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None,
                            help="Output path (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(f"No salon with id {options['salon_id']}.") from exc
        day = _parse_date(options.get("date"), "date")
        if day is None:
            raise CommandError("--date is required.")
        try:
            if fmt == "json":
                rows = export_prior_daily_sales(salon, day)
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_prior_daily_sales_csv(salon, day)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(f"Cannot write export file {options['output']}: {exc}") from exc
        else:
            self.stdout.write(text, ending="")
