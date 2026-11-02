"""Export a salon's prior-period stock movement summary as CSV.

Usage: python manage.py export_prior_movement_summary
    --salon-id ID --start-date YYYY-MM-DD --end-date YYYY-MM-DD
    [--output PATH]

Thin wrapper around :mod:`catalog.prior_movement_summary_export`:
salon resolved by id, dates parsed and passed verbatim (``start``
/ ``end`` are the current window's inclusive bounds; the prior
window is the equal-length window immediately before it); CSV
written unchanged to ``--output`` or stdout. Both dates are
required; unknown salon, unparseable / missing date, or a
service error (e.g. reversed range) raises ``CommandError``.
Founding rule (Exit Principle): anything a salon can enter, it
can fully export.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from catalog.prior_movement_summary_export import (
    export_prior_movement_summary_csv,
)
from saloncore.models import Salon


def _parse_date(value):
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
            f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc


class Command(BaseCommand):
    help = "Export a salon's prior-period stock movement summary as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", required=True, type=int,
                            help="ID of the salon to export.")
        parser.add_argument(
            "--start-date", "--start", dest="start_date", default=None,
            help="First day of the current window, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--end-date", "--end", dest="end_date", default=None,
            help="Last day of the current window, YYYY-MM-DD (inclusive).")
        parser.add_argument("--output", default=None,
                            help="Path of the CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        start = _parse_date(options["start_date"])
        end = _parse_date(options["end_date"])
        try:
            text = export_prior_movement_summary_csv(start, end, salon=salon)
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
