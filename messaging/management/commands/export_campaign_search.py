"""Export one salon's campaign search results as CSV.

Usage:
    python manage.py export_campaign_search --salon-id ID
        [--term TEXT] [--status STATUS] [--channel CHANNEL]
        [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--output PATH]

Thin wrapper around
:func:`messaging.campaign_search_export.export_campaign_search_csv`:
the salon is resolved by id, dates are parsed to ``date``
objects, and every filter is passed verbatim -- its CSV text
is written unchanged, to ``--output`` when given and to
stdout otherwise. Unknown salon, a service error (e.g. a
reversed range), or an unwritable output raises
``CommandError``. Read-only; no provider SDK or name here.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from messaging.campaign_search_export import export_campaign_search_csv
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
    help = "Export one salon's campaign search results as CSV."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon whose campaigns to export.")
        parser.add_argument("--term", dest="term", default=None,
                            help="Campaign-name fragment (case-insensitive).")
        parser.add_argument("--name", dest="name", default=None,
                            help="Alias for --term.")
        parser.add_argument("--query", dest="query", default=None,
                            help="Alias for --term.")
        parser.add_argument("--fragment", dest="fragment", default=None,
                            help="Alias for --term.")
        parser.add_argument("--status", dest="status", default=None,
                            help="Campaign status value to filter by.")
        parser.add_argument("--channel", dest="channel", default=None,
                            help="Campaign channel value to filter by.")
        parser.add_argument("--start", dest="start", type=_parse_date,
                            default=None, help="First day, YYYY-MM-DD.")
        parser.add_argument("--start-date", dest="start_date",
                            type=_parse_date, default=None,
                            help="Alias for --start.")
        parser.add_argument("--date-from", dest="date_from",
                            type=_parse_date, default=None,
                            help="Alias for --start.")
        parser.add_argument("--end", dest="end", type=_parse_date,
                            default=None, help="Last day, YYYY-MM-DD.")
        parser.add_argument("--end-date", dest="end_date", type=_parse_date,
                            default=None, help="Alias for --end.")
        parser.add_argument("--date-to", dest="date_to", type=_parse_date,
                            default=None, help="Alias for --end.")
        parser.add_argument("--output", default=None,
                            help="Path to write the CSV to (default: stdout).")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        term = _first(options, "term", "name", "query", "fragment")
        start = _coerce_date(
            _first(options, "start", "start_date", "date_from"), "start")
        end = _coerce_date(
            _first(options, "end", "end_date", "date_to"), "end")
        try:
            text = export_campaign_search_csv(
                salon, term, status=options.get("status"),
                channel=options.get("channel"), start=start, end=end,
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
