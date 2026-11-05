"""Export one salon's prior-period no-show report comparison as CSV or JSON.

Usage: python manage.py export_prior_noshow --salon-id ID
    --start-date YYYY-MM-DD --end-date YYYY-MM-DD
    [--now ISO-8601-DATETIME] [--format json|csv] [--output PATH]
Thin wrapper around :mod:`bookings.prior_noshow_export`;
unknown salon, bad/missing date, or service error -> CommandError.
For ``--format csv`` (the default) the CSV output is exactly
as before, byte-identical; for ``--format json`` the same
arguments are passed to
:func:`bookings.prior_noshow_export.prior_noshow_rows` (the
dict list the CSV is built from) and its rows are serialised
as JSON via ``DjangoJSONEncoder``, so the two formats can
never disagree.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from bookings.prior_noshow_export import export_prior_noshow_csv, prior_noshow_rows
from saloncore.models import Salon

_FORMATS = ("json", "csv")

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
        raise CommandError(f"Invalid {label} {value!r}; expected YYYY-MM-DD.") from exc

def _datetime_from_string(value):
    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(text)

def _parse_datetime(value):
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid datetime {value!r}; expected ISO-8601.") from exc

def _coerce_now(value):
    if value is None or isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(
            value, datetime.time.min, tzinfo=datetime.timezone.utc)
    try:
        return _datetime_from_string(value)
    except ValueError as exc:
        raise CommandError(
            f"Invalid now {value!r}; expected ISO-8601 datetime.") from exc

class Command(BaseCommand):
    help = "Export one salon's prior-period no-show report comparison as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True, help="Id of the salon to export.")
        parser.add_argument("--start-date", "--date-from", "--from-date", "--start", dest="start_date", default=None, help="Inclusive first day of the current window, YYYY-MM-DD.")
        parser.add_argument("--end-date", "--date-to", "--to-date", "--end", dest="end_date", default=None, help="Inclusive last day of the current window, YYYY-MM-DD.")
        parser.add_argument("--now", dest="now", type=_parse_datetime, default=None, help="Reference instant for \"past\", ISO-8601 (default: the service's own default).")
        parser.add_argument("--format", dest="format", default="csv", choices=_FORMATS, help="Export format: csv (default) or json.")
        parser.add_argument("--output", default=None, help="Path to write the export to (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        start_raw = options.get("start_date") or options.get("date_from")
        end_raw = options.get("end_date") or options.get("date_to")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(f"No salon with id {options['salon_id']}.") from exc
        start_date = _parse_date(start_raw, "start date")
        end_date = _parse_date(end_raw, "end date")
        if start_date is None or end_date is None:
            raise CommandError("Both --start-date and --end-date are required.")
        now = _coerce_now(options.get("now"))
        try:
            if fmt == "json":
                rows = prior_noshow_rows(salon, start_date, end_date, now=now)
                text = json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_prior_noshow_csv(salon, start_date, end_date, now=now)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if options.get("output"):
            try:
                with open(options["output"], "w", encoding="utf-8", newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(f"Cannot write export file {options['output']}: {exc}") from exc
        else:
            self.stdout.write(text, ending="")
