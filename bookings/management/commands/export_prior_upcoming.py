"""Export one salon's prior (elapsed-window) upcoming counts as CSV.

Usage: python manage.py export_prior_upcoming --salon-id ID
    [--start-date YYYY-MM-DD] [--days N] [--output PATH]
Thin wrapper around :mod:`bookings.prior_upcoming_export`;
unknown salon, bad start, bad window, or service error ->
CommandError.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.prior_upcoming_export import export_prior_upcoming_csv
from bookings.upcoming import DEFAULT_DAYS
from saloncore.models import Salon

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
            "counts comparison as CSV.")

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--start-date", "--start", "--date",
                            dest="start", type=_parse_date, default=None,
                            help="Forward window start, YYYY-MM-DD.")
        parser.add_argument("--days", "--horizon-days", dest="days",
                            type=int, default=DEFAULT_DAYS,
                            help="Window size in days (default: %(default)s).")
        parser.add_argument("--output", default=None,
                            help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
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
