"""Export one salon's upcoming appointments as CSV.

Usage:
    python manage.py export_upcoming --salon-id ID
        [--start-date YYYY-MM-DD] [--days N] [--output PATH]

Thin wrapper around the existing
:func:`bookings.upcoming_export.export_upcoming_csv` service:
the salon is resolved by id, the start is parsed to a
``datetime.date``, and both are passed to the service verbatim
as ``export_upcoming_csv(salon, start, days)`` -- its CSV text
is written unchanged, to ``--output`` when given and to stdout
otherwise. ``--start-date`` and ``--days`` are optional and
default exactly as the service defines them (``start=None``,
``days=DEFAULT_DAYS``). This command adds no export logic of
its own, so command and service output can never disagree --
one source of truth. Backend only; read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.upcoming import DEFAULT_DAYS
from bookings.upcoming_export import export_upcoming_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_start(value):
    if value is None or isinstance(
            value, (datetime.date, datetime.datetime)):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid start date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's upcoming appointments as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose upcoming appointments to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date", dest="start",
            type=_parse_date, default=None,
            help="Window start, YYYY-MM-DD (default: the service's "
                 "own default).",
        )
        parser.add_argument(
            "--days", "--horizon-days", dest="days",
            type=int, default=DEFAULT_DAYS,
            help="Window size in days (default: %(default)s).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the CSV to (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        start = _coerce_start(options.get("start"))
        try:
            days = int(options.get("days", DEFAULT_DAYS))
        except (TypeError, ValueError) as exc:
            raise CommandError(
                f"Invalid days {options.get('days')!r}; expected an integer."
            ) from exc
        text = export_upcoming_csv(salon, start, days)
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
