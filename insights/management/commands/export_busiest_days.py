"""Export a salon's busiest days as CSV.

Usage:
    python manage.py export_busiest_days --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--output PATH]

Thin wrapper around the existing
:func:`insights.busiest_export.export_busiest_days_csv`
service: the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and both are passed to the service
verbatim — its CSV text is written unchanged, to ``--output``
when given and to stdout otherwise. The service takes no extra
keyword arguments, so this command exposes none. A reversed
range behaves exactly as the service defines it (seven zeroed
weekday rows). Dates mean whole local days in the salon's
timezone, inclusive at both ends, exactly as the service
defines them. Read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from insights.busiest_export import export_busiest_days_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's busiest days as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose busiest days to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            type=_parse_date, required=True,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            type=_parse_date, required=True,
            help="Last day of the range, YYYY-MM-DD (inclusive).",
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
        text = export_busiest_days_csv(
            salon, options["start_date"], options["end_date"]
        )
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
