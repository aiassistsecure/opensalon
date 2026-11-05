"""Export a salon's prior-period online cancellations as CSV or JSON.

Usage: python manage.py export_prior_cancellations --salon-id ID
--start-date YYYY-MM-DD --end-date YYYY-MM-DD
[--format json|csv] [--output PATH]
Thin wrapper around
:mod:`onlinebooking.prior_cancellations_export`: for
``--format csv`` (the default) the CSV from
``export_prior_cancellations_csv`` is written unchanged to
``--output`` or stdout, byte-identical to before; for
``--format json`` the same arguments are passed to the dict
service ``export_prior_cancellations`` (beside its CSV twin)
and its rows are serialised as JSON, so the two formats can
never disagree. Unknown salon, unparseable/missing date, or
service error raises ``CommandError``. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from onlinebooking.prior_cancellations_export import (
    export_prior_cancellations,
    export_prior_cancellations_csv,
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
    help = "Export a salon's prior-period online cancellations as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--start-date", "--start", "--date-from",
                            dest="start_date", default=None,
                            help="First day, YYYY-MM-DD (inclusive).")
        parser.add_argument("--end-date", "--end", "--date-to",
                            dest="end_date", default=None,
                            help="Last day, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
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
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")
        if start_date is None or end_date is None:
            raise CommandError(
                "Both --start-date and --end-date are required.")
        try:
            if fmt == "json":
                rows = export_prior_cancellations(salon, start_date, end_date)
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_prior_cancellations_csv(salon, start_date, end_date)
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
