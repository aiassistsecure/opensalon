"""Export one salon's prior (elapsed-window) upcoming counts as CSV or JSON.

Usage: python manage.py export_prior_upcoming --salon-id ID
    [--start-date YYYY-MM-DD] [--days N] [--format csv|json]
    [--output PATH]
Thin wrapper around :mod:`bookings.prior_upcoming_export`;
unknown salon, bad start, bad window, or service error ->
CommandError. For ``--format csv`` (the default) the CSV output
is exactly as before, byte-identical; for ``--format json`` the
same arguments are passed to
:func:`bookings.prior_upcoming_export.export_prior_upcoming_dict`
and its wrapper dict is serialised verbatim as JSON via
``DjangoJSONEncoder`` (not the bare rows list).
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from bookings.prior_upcoming_export import (
    export_prior_upcoming_csv,
    export_prior_upcoming_dict,
)
from bookings.upcoming import DEFAULT_DAYS
from saloncore.models import Salon

_FORMATS = ("json", "csv")

def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc

def _coerce_start(value):
    if value is None or isinstance(value, (datetime.date, datetime.datetime)):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid start date {value!r}; expected YYYY-MM-DD.") from exc

class Command(BaseCommand):
    help = ("Export one salon's prior (elapsed-window) upcoming "
            "counts comparison as CSV (default) or JSON.")

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--start-date", "--start", "--date",
                            dest="start", type=_parse_date, default=None,
                            help="Forward window start, YYYY-MM-DD.")
        parser.add_argument("--days", "--horizon-days", dest="days",
                            type=int, default=DEFAULT_DAYS,
                            help="Window size in days (default: %(default)s).")
        parser.add_argument("--format", dest="format", default="csv",
                            choices=_FORMATS,
                            help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None,
                            help="Path to write the export to (default: stdout).")

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
        start = _coerce_start(options.get("start"))
        try:
            days = int(options.get("days", DEFAULT_DAYS))
        except (TypeError, ValueError) as exc:
            raise CommandError(
                f"Invalid days {options.get('days')!r}.") from exc
        try:
            if fmt == "json":
                payload = export_prior_upcoming_dict(salon, start, days)
                text = json.dumps(
                    payload, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_prior_upcoming_csv(salon, start, days)
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
