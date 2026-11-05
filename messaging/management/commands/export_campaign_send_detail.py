"""Export one salon's campaign sends, one row per send, as CSV or JSON.

Usage: python manage.py export_campaign_send_detail
    --salon-id ID --date-from YYYY-MM-DD [--date-to YYYY-MM-DD]
    [--campaign-id ID] [--format json|csv] [--output PATH]

Thin wrapper around
:func:`messaging.campaign_send_detail.export_campaign_send_detail_csv`
and :func:`messaging.campaign_send_detail.export_campaign_send_detail`:
salon resolved by id, dates parsed and passed verbatim. For
``--format csv`` (the default) the CSV is written unchanged to
--output or stdout; for ``--format json`` the same dict rows are
serialised as JSON via ``DjangoJSONEncoder``, so the two formats
can never disagree -- one source of truth. Distinct from the
aggregate commands ``export_campaign_send_totals`` and
``export_campaign_send_totals_detail``. Unknown salon / unknown
format / service error / unwritable output raise CommandError.
Read-only.

With ``--campaign-id`` the export is narrowed to that one
campaign's sends: the campaign is resolved by id within the
salon (a campaign from another salon, or an unknown id, is a
``CommandError``), and the resolved campaign is passed to the
service as its optional ``campaign`` argument. Without
``--campaign-id`` the command exports the whole salon, exactly
as before.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from messaging.campaign_send_detail import (
    export_campaign_send_detail,
    export_campaign_send_detail_csv,
)
from messaging.models import Campaign
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
    help = "Export one salon's campaign sends, row per send, as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
            help="Id of the salon whose campaign sends to export.")
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
        parser.add_argument("--campaign-id", type=int, default=None,
            help="Id of the campaign (in the salon) whose sends "
                 "to export (default: all campaigns).")
        parser.add_argument("--format", dest="format", default="csv",
            choices=_FORMATS,
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
        campaign = None
        if options.get("campaign_id") is not None:
            try:
                campaign = Campaign.objects.get(
                    pk=options["campaign_id"], salon=salon)
            except Campaign.DoesNotExist as exc:
                raise CommandError(
                    f"No campaign with id {options['campaign_id']} "
                    f"for salon {salon.pk}."
                ) from exc
        try:
            if fmt == "json":
                rows = export_campaign_send_detail(
                    salon, date_from, date_to, campaign=campaign,
                )
                text = json.dumps(
                    rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_campaign_send_detail_csv(
                    salon, date_from, date_to, campaign=campaign,
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
