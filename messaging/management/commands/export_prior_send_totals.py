"""Export a salon's prior-period send totals comparison as CSV.

Usage:
    python manage.py export_prior_send_totals --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--output PATH]

Thin wrapper around
:func:`messaging.prior_send_totals_export.export_prior_send_totals_csv`:
salon resolved by id, dates parsed and passed verbatim, CSV
written unchanged to ``--output`` or stdout -- no export logic
of its own, one source of truth. Both dates required; unknown
salon, unparseable/missing date, or service error raises
``CommandError``. Read-only. Core stays provider-agnostic --
no provider SDK, field, or name appears here.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from messaging.prior_send_totals_export import export_prior_send_totals_csv
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
    help = "Export a salon's prior-period send totals comparison as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose comparison to export.")
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            default=None,
            help="First day of the current window, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None,
            help="Last day of the current window, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--output", default=None,
            help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")
        if start_date is None or end_date is None:
            raise CommandError("Both --start-date and --end-date are required.")
        try:
            text = export_prior_send_totals_csv(salon, start_date, end_date)
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
