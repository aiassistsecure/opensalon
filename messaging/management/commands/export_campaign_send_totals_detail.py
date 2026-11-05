"""Export one salon's campaign-send totals detail as CSV or JSON.

Usage: python manage.py export_campaign_send_totals_detail
    --salon-id ID --date-from YYYY-MM-DD [--date-to YYYY-MM-DD]
    [--format json|csv] [--output PATH]

Thin wrapper around
:func:`messaging.campaign_send_export.export_campaign_send_totals_detail_csv`
and its dict twin
:func:`messaging.campaign_send_export.export_campaign_send_totals_detail`:
salon resolved by id, dates parsed and passed verbatim; for
``--format csv`` (the default) its CSV text is written
unchanged, exactly as before; for ``--format json`` the same
dict rows are serialised as JSON. Output goes to --output
or stdout. Distinct from the summary command
``export_campaign_send_totals``. Unknown salon / unknown
``--format`` / service error / unwritable output raise
CommandError. Read-only; no provider SDK, field, or name
appears here.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from messaging.campaign_send_export import (
    export_campaign_send_totals_detail,
    export_campaign_send_totals_detail_csv,
)

from saloncore.models import Salon

_FORMATS = ("json", "csv")


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
    help = "Export one salon's campaign-send totals detail as CSV or JSON."

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
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None,
            help="Path to write the export to (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
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
            if fmt == "json":
                rows = export_campaign_send_totals_detail(
                    salon, date_from, date_to,
                )
                text = json.dumps(rows, indent=2) + "\n"
            else:
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
