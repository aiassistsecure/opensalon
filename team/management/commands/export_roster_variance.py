"""Export one salon's rostered-vs-actual variance as CSV.

Usage:
    python manage.py export_roster_variance --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--output PATH]

Thin wrapper around
:func:`team.variance_export.export_roster_variance_csv`: the
salon is resolved by id, dates are parsed, and all three are
passed to the service verbatim. An unknown salon, a missing or
unparseable date, or a reversed range raises ``CommandError``.
Backend only. Read-only.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.variance_export import export_roster_variance_csv


def _parse_date(value, label):
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if value in (None, ""):
        raise CommandError(f"Missing {label}; expected YYYY-MM-DD.")
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD.") from exc


class Command(BaseCommand):
    help = "Export one salon's rostered-vs-actual variance as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", required=True, type=int,
                            help="Id of the salon to export.")
        parser.add_argument("--start-date", dest="start_date", required=True,
                            help="First day, YYYY-MM-DD (inclusive).")
        parser.add_argument("--end-date", dest="end_date", required=True,
                            help="Last day, YYYY-MM-DD (inclusive).")
        parser.add_argument("--output", default=None,
                            help="CSV file to write (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None
        start = _parse_date(options.get("start_date"), "start date")
        end = _parse_date(options.get("end_date"), "end date")
        try:
            text = export_roster_variance_csv(salon, start, end)
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
