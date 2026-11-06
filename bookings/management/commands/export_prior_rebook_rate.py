"""Export one salon's prior-period rebook rate comparison as CSV or JSON.

Usage: python manage.py export_prior_rebook_rate --salon-id ID
    --start-date YYYY-MM-DD --end-date YYYY-MM-DD
    [--format json|csv] [--output PATH]

Thin wrapper around :mod:`bookings.prior_rebook_rate_export`:
salon resolved by id, dates parsed and passed verbatim. For
``--format csv`` (the default) it writes
:func:`bookings.prior_rebook_rate_export.export_prior_rebook_rate_csv`'s
CSV string as-is, so the historical CSV output is byte-identical;
for ``--format json`` it serialises the same dict rows from
:func:`bookings.prior_rebook_rate_export.export_prior_rebook_rate_rows`
-- the same rows the CSV is built from -- as JSON via
``DjangoJSONEncoder``. Output written unchanged to ``--output``
or stdout. Both dates are required; unknown salon, unparseable
/ missing date, unknown format, or a service error (e.g.
reversed range) raises ``CommandError``.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from bookings.prior_rebook_rate_export import (
    export_prior_rebook_rate_csv,
    export_prior_rebook_rate_rows,
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
            f"Invalid {label} {value!r}; expected YYYY-MM-DD.") from exc


class Command(BaseCommand):
    help = "Export one salon's prior-period rebook rate comparison as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument(
            "--start-date", "--date-from", "--from-date", "--start",
            dest="start_date", default=None,
            help="Inclusive first day of the current window, YYYY-MM-DD.")
        parser.add_argument(
            "--end-date", "--date-to", "--to-date", "--end",
            dest="end_date", default=None,
            help="Inclusive last day of the current window, YYYY-MM-DD.")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None,
                            help="Path to write the export to (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        # call_command may pass the rebook-style dests instead.
        start_raw = options.get("start_date") or options.get("date_from")
        end_raw = options.get("end_date") or options.get("date_to")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        start_date = _parse_date(start_raw, "start date")
        end_date = _parse_date(end_raw, "end date")
        if start_date is None or end_date is None:
            raise CommandError("Both --start-date and --end-date are required.")
        try:
            if fmt == "json":
                text = json.dumps(
                    export_prior_rebook_rate_rows(salon, start_date, end_date),
                    indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_prior_rebook_rate_csv(salon, start_date, end_date)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options.get("output"):
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
