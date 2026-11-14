"""Export prior-period popularity/client-value comparison as CSV or JSON.

Usage: python manage.py export_prior_popularity_client_value
--salon-id ID --kind popularity|client_value
--start-date YYYY-MM-DD --end-date YYYY-MM-DD
[--format json|csv] [--output PATH].
Thin wrapper around
:mod:`insights.prior_popularity_client_value`: for
``--format csv`` (the default) its CSV is written unchanged
to --output or stdout, exactly as before; for
``--format json`` it serialises the SAME dict rows for the
selected ``--kind`` (from the matching dict-row function in
that module, the same rows the CSV is built from) as JSON
via ``DjangoJSONEncoder``, so the two formats can never
disagree. Unknown salon, bad/missing dates, unknown format,
or a service error raises CommandError. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from insights.prior_popularity_client_value import (
    export_prior_client_value,
    export_prior_client_value_csv,
    export_prior_popularity,
    export_prior_popularity_csv,
)
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
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a prior-period popularity or client-value comparison as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True, help="Id of the salon to export.")
        parser.add_argument("--kind", choices=["popularity", "client_value"], default="popularity", help="Which breakdown to export.")
        parser.add_argument("--start-date", "--start", "--date-from", dest="start_date", default=None, help="First day of the current window.")
        parser.add_argument("--end-date", "--end", "--date-to", dest="end_date", default=None, help="Last day of the current window.")
        parser.add_argument("--format", dest="format", default="csv", choices=_FORMATS, help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None, help="Path to write the export to (default: stdout).")

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
        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")
        if start_date is None or end_date is None:
            raise CommandError(
                "Both --start-date and --end-date are required.")
        try:
            if fmt == "json":
                rows = (export_prior_popularity(salon, start_date, end_date)
                        if options["kind"] == "popularity"
                        else export_prior_client_value(salon, start_date,
                                                        end_date))
                text = json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                fn = (export_prior_popularity_csv
                      if options["kind"] == "popularity"
                      else export_prior_client_value_csv)
                text = fn(salon, start_date, end_date)
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
