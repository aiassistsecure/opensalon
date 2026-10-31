"""Export one salon's reminder-send search results as CSV.

Usage:
    python manage.py export_send_search --salon-id ID
        [--term TEXT] [--channel CHANNEL] [--status STATUS]
        [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--output PATH]

Thin wrapper around the existing
:func:`messaging.send_search_export.export_search_sends_csv`
service: the salon is resolved by id, the optional dates are
parsed to ``datetime.date`` objects, and every filter is
passed to the service verbatim -- its CSV text is written
unchanged, to ``--output`` when given and to stdout otherwise.
This command adds no export logic of its own, so command and
service output can never disagree -- one source of truth.

Invalid input -- an unknown salon or a service error (e.g. a
reversed range) -- raises ``CommandError``, as does an
unwritable ``--output`` path. Read-only. Core stays
provider-agnostic -- no provider SDK, field, or name appears
here.
"""
import argparse
import datetime

from django.core.management.base import BaseCommand, CommandError

from messaging.send_search_export import export_search_sends_csv
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
    help = "Export one salon's reminder-send search results as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose sends to export.",
        )
        parser.add_argument(
            "--term", dest="term", default=None,
            help="Client-name fragment to match (case-insensitive).",
        )
        parser.add_argument(
            "--client-name", dest="client_name", default=None,
            help="Alias for --term.",
        )
        parser.add_argument(
            "--query", dest="query", default=None,
            help="Alias for --term.",
        )
        parser.add_argument(
            "--name", dest="name", default=None,
            help="Alias for --term.",
        )
        parser.add_argument(
            "--fragment", dest="fragment", default=None,
            help="Alias for --term.",
        )
        parser.add_argument(
            "--channel", dest="channel", default=None,
            help="Channel value to filter by.",
        )
        parser.add_argument(
            "--status", dest="status", default=None,
            help="Status value to filter by.",
        )
        parser.add_argument(
            "--start", dest="start", type=_parse_date, default=None,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--start-date", dest="start_date", type=_parse_date,
            default=None, help="Alias for --start.",
        )
        parser.add_argument(
            "--date-from", dest="date_from", type=_parse_date,
            default=None, help="Alias for --start.",
        )
        parser.add_argument(
            "--end", dest="end", type=_parse_date, default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", dest="end_date", type=_parse_date,
            default=None, help="Alias for --end.",
        )
        parser.add_argument(
            "--date-to", dest="date_to", type=_parse_date,
            default=None, help="Alias for --end.",
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
        term = _first(
            options, "term", "client_name", "query", "name", "fragment")
        start = _coerce_date(
            _first(options, "start", "start_date", "date_from"), "start")
        end = _coerce_date(
            _first(options, "end", "end_date", "date_to"), "end")
        try:
            text = export_search_sends_csv(
                salon, term, channel=options.get("channel"),
                status=options.get("status"), start=start, end=end,
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
