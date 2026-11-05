"""Export one salon's prior-period new-client comparison as CSV or JSON.

Usage: python manage.py export_prior_new_clients --salon-id ID
    --start-date YYYY-MM-DD --end-date YYYY-MM-DD
    [--format json|csv] [--output PATH]

Thin wrapper around ``clients.prior_new_clients_export``: salon
resolved by id, dates parsed and passed verbatim; for
``--format csv`` (the default) the CSV from
:func:`clients.prior_new_clients_export.export_prior_new_clients_csv`
is written unchanged to ``--output`` or stdout; for
``--format json`` the SAME dict rows from
:func:`clients.prior_new_clients_export.export_prior_new_clients`
are serialised via ``DjangoJSONEncoder`` (indent=2, trailing
newline), so the two formats can never disagree. Both dates
required; unknown salon, unparseable/missing date, unknown
format, or a service error (e.g. reversed range) raises
``CommandError``.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from clients.prior_new_clients_export import (
    export_prior_new_clients,
    export_prior_new_clients_csv,
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
    help = ("Export one salon's prior-period new-client count comparison "
            "as CSV (default) or JSON.")

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="ID of the salon to export.")
        parser.add_argument("--start-date", "--start", "--date-from",
                            dest="start_date", default=None,
                            help="First day of the current window, YYYY-MM-DD.")
        parser.add_argument("--end-date", "--end", "--date-to",
                            dest="end_date", default=None,
                            help="Last day of the current window, YYYY-MM-DD.")
        parser.add_argument("--format", dest="format", default="csv",
                            choices=_FORMATS,
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
        except Salon.DoesNotExist:
            raise CommandError(f"No salon with id {options['salon_id']}.") from None
        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")
        if start_date is None or end_date is None:
            raise CommandError("Both --start-date and --end-date are required.")
        try:
            if fmt == "json":
                rows = export_prior_new_clients(salon, start_date, end_date)
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_prior_new_clients_csv(salon, start_date, end_date)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}") from exc
        else:
            self.stdout.write(text, ending="")
