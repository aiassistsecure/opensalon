"""Export prior-period attach-rate/category-mix comparison as CSV.

Usage: python manage.py export_prior_attach_category --salon-id ID
--kind attach|category_mix --start-date YYYY-MM-DD
--end-date YYYY-MM-DD [--output PATH]. Thin wrapper around
:mod:`insights.prior_attach_category` — its CSV is written
unchanged to --output or stdout. Unknown salon, bad/missing
dates, or a service error raises CommandError. Read-only.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from insights.prior_attach_category import (
    export_prior_attach_csv,
    export_prior_category_mix_csv,
)
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
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a prior-period attach-rate or category-mix comparison."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True, help="Id of the salon to export.")
        parser.add_argument("--kind", choices=["attach", "category_mix"], default="attach", help="Which comparison to export.")
        parser.add_argument("--start-date", "--start", "--date-from", dest="start_date", default=None, help="First day of the current window.")
        parser.add_argument("--end-date", "--end", "--date-to", dest="end_date", default=None, help="Last day of the current window.")
        parser.add_argument("--output", default=None, help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")
        if start_date is None or end_date is None:
            raise CommandError(
                "Both --start-date and --end-date are required.")
        fn = (export_prior_attach_csv if options["kind"] == "attach"
              else export_prior_category_mix_csv)
        try:
            text = fn(salon, start_date, end_date)
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
