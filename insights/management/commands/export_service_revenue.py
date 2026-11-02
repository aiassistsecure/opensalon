"""Export a salon's per-service revenue report as CSV.

Usage:
    python manage.py export_service_revenue --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--output PATH]

Thin wrapper around
:func:`insights.service_revenue_export.export_service_revenue_csv`:
salon resolved by id, dates parsed to ``datetime.date``, both
passed verbatim — CSV written unchanged to ``--output`` or stdout.
No export logic of its own (one source of truth). Unknown salon,
unparseable date, or service error raises ``CommandError``.
Dates are whole local days in the salon's timezone, inclusive.
Read-only.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from insights.service_revenue_export import export_service_revenue_csv
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
    help = "Export a salon's per-service revenue report as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose per-service revenue "
                 "report to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            default=None, required=False,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None, required=False,
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
        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")
        if start_date is None or end_date is None:
            raise CommandError(
                "Both --start-date and --end-date are required."
            )
        try:
            text = export_service_revenue_csv(
                salon, start_date, end_date
            )
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
