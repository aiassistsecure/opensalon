"""Export one salon's rebook rate summary as CSV.

Usage:
    python manage.py export_rebook_rate --salon-id ID
        --date-from YYYY-MM-DD [--date-to YYYY-MM-DD]
        [--output PATH]

Thin wrapper around
:func:`bookings.rebook_rate_export.export_rebook_rate_csv`:
the salon is resolved by id, dates are parsed, and both are
passed to the service verbatim — its CSV text is written
unchanged, to ``--output`` when given and to stdout otherwise.
Backend only; read-only.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.rebook_rate_export import export_rebook_rate_csv
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc


class Command(BaseCommand):
    help = "Export one salon's rebook rate summary as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--date-from", "--from-date", "--start-date",
                            dest="date_from", type=_parse_date, default=None,
                            help="Inclusive first day, YYYY-MM-DD.")
        parser.add_argument("--date-to", "--to-date", "--end-date",
                            dest="date_to", type=_parse_date, default=None,
                            help="Inclusive last day, YYYY-MM-DD.")
        parser.add_argument("--output", default=None,
                            help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        if options.get("date_from") is None:
            raise CommandError("A --date-from is required.")
        try:
            text = export_rebook_rate_csv(
                salon, options["date_from"], options.get("date_to"))
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
