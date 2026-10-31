"""Export a salon's price-change audit history as CSV.

Usage:
    python manage.py export_price_changes --salon-id ID
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--output PATH]

Thin wrapper around :func:`saloncore.price_change_export.export_price_changes_csv`
-- that service is the one source of truth for the price-change
export; this command only resolves the salon, parses the optional
dates to ``datetime.date`` objects, delegates to the service
verbatim, and writes the CSV it returns (to ``--output`` when
given, otherwise to stdout). Date semantics are exactly the
service's: start-inclusive, end covers the whole end day.
Backend only; read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from saloncore.price_change_export import export_price_changes_csv


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's price-change audit history as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose price changes to export.",
        )
        parser.add_argument(
            "--start-date", dest="start_date", type=_parse_date,
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--end-date", dest="end_date", type=_parse_date,
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None
        csv_text = export_price_changes_csv(
            salon, start=options["start_date"], end=options["end_date"])
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8", newline="") as fh:
                    fh.write(csv_text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(csv_text, ending="")
