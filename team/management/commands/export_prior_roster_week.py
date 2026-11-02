"""Export one salon's prior-week roster week comparison as CSV.

Usage: python manage.py export_prior_roster_week --salon-id ID
    --week-start YYYY-MM-DD [--output PATH]
Thin wrapper around :mod:`team.prior_roster_week_export`; unknown
salon, bad / missing dates raises ``CommandError``.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.prior_roster_week_export import export_prior_roster_week_csv


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
    help = "Export one salon's prior-week roster week comparison as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument(
            "--week-start", "--start-date", "--date", "--start",
            dest="week_start", default=None,
            help="First day of the current week, YYYY-MM-DD (its Monday).")
        parser.add_argument("--output", default=None,
                            help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        week_start = _parse_date(options.get("week_start"), "week-start date")
        if week_start is None:
            raise CommandError("--week-start is required.")
        try:
            text = export_prior_roster_week_csv(salon, week_start)
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
