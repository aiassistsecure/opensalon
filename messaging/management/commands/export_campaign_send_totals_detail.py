"""Export one salon's campaign-send totals detail as CSV.

Usage: python manage.py export_campaign_send_totals_detail
    --salon-id ID --date-from YYYY-MM-DD [--date-to YYYY-MM-DD]
    [--output PATH]

Thin wrapper around
:func:`messaging.campaign_send_export.export_campaign_send_totals_detail_csv`:
salon resolved by id, dates parsed and passed verbatim, CSV
written unchanged to --output or stdout. Distinct from the
summary command ``export_campaign_send_totals``. Unknown
salon / service error / unwritable output raise CommandError.
Read-only; no provider SDK, field, or name appears here.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from messaging.campaign_send_export import (
    export_campaign_send_totals_detail_csv,
)
from saloncore.models import Salon


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value, label):
    if value is None or isinstance(
            value, (datetime.date, datetime.datetime)):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


def _first(options, *keys):
    for key in keys:
        value = options.get(key)
        if value is not None:
            return value
    return None


class Command(BaseCommand):
    help = "Export one salon's campaign-send totals detail as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
            help="Id of the salon whose campaign send totals to export.")
        parser.add_argument("--date-from", dest="date_from", type=_parse_date,
            default=None, help="First day, YYYY-MM-DD (inclusive).")
        parser.add_argument("--start", dest="start", type=_parse_date,
            default=None, help="Alias for --date-from.")
        parser.add_argument("--start-date", dest="start_date", type=_parse_date,
            default=None, help="Alias for --date-from.")
        parser.add_argument("--date-to", dest="date_to", type=_parse_date,
            default=None, help="Last day, YYYY-MM-DD (inclusive).")
        parser.add_argument("--end", dest="end", type=_parse_date,
            default=None, help="Alias for --date-to.")
        parser.add_argument("--end-date", dest="end_date", type=_parse_date,
            default=None, help="Alias for --date-to.")
        parser.add_argument("--output", default=None,
            help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        date_from = _coerce_date(
            _first(options, "date_from", "start", "start_date"),
            "date_from")
        date_to = _coerce_date(
            _first(options, "date_to", "end", "end_date"), "date_to")
        try:
            text = export_campaign_send_totals_detail_csv(
                salon, date_from, date_to,
            )
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
