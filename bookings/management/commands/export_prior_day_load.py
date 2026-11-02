"""Export one salon's prior (same-weekday) day load as CSV.

Usage: python manage.py export_prior_day_load --salon-id ID
    --date YYYY-MM-DD [--output PATH]
Thin wrapper around :mod:`bookings.prior_day_load_export`;
unknown salon, bad/missing date, or service error -> CommandError.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from bookings.prior_day_load_export import export_prior_day_load_csv
from saloncore.models import Salon


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
    help = "Export one salon's prior (same-weekday) day load comparison as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--date", "--day", dest="date", default=None,
                            help="Day to report, YYYY-MM-DD.")
        parser.add_argument("--start-date", dest="start_date", default=None,
                            help="Alias for --date, YYYY-MM-DD.")
        parser.add_argument("--end-date", dest="end_date", default=None,
                            help="Alias for --date, YYYY-MM-DD.")
        parser.add_argument("--output", default=None,
                            help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
        raw = (options.get("date") or options.get("start_date")
               or options.get("end_date"))
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        day = _parse_date(raw, "date")
        if day is None:
            raise CommandError("--date is required.")
        try:
            text = export_prior_day_load_csv(salon, day)
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
