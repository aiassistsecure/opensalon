"""Export a salon's week / month revenue rollup as CSV.

Usage: python manage.py export_rollup --salon-id ID
    [--granularity week|month] [--days N]
    [--end-date YYYY-MM-DD] [--output PATH]

Thin wrapper around :func:`insights.rollup_export.export_rollup_csv`:
options pass to the service verbatim, its CSV is written unchanged
(to ``--output`` or stdout). Unknown salon, bad date/days, or unknown
granularity raises ``CommandError``. Read-only.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from insights.rollup_export import export_rollup_csv
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
            f"Invalid end date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _parse_days(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise CommandError(f"Invalid days {value!r}; expected an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid days {value!r}; expected an integer."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's week / month revenue rollup as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose revenue rollup to export.")
        parser.add_argument(
            "--granularity", default="week",
            help="Rollup granularity: week or month.")
        parser.add_argument(
            "--days", type=int, default=None,
            help="Days in the window (default: service default).")
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None,
            help="Last day of the window, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--output", default=None,
            help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        days = _parse_days(options["days"])
        end_date = _parse_date(options["end_date"])
        try:
            text = export_rollup_csv(
                salon, granularity=options["granularity"], days=days,
                end_date=end_date)
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
