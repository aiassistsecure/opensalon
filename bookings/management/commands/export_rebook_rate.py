"""Export one salon's rebook rate summary as CSV or JSON.

Usage:
    python manage.py export_rebook_rate --salon-id ID
        --date-from YYYY-MM-DD [--date-to YYYY-MM-DD]
        [--format json|csv] [--output PATH]

Thin wrapper around :mod:`bookings.rebook_rate_export`:
the salon is resolved by id, dates are parsed, and both are
passed to the service verbatim. For ``--format csv`` (the
default) it writes
:func:`bookings.rebook_rate_export.export_rebook_rate_csv`'s
CSV text, exactly as before, byte-identical; for
``--format json`` it serialises the same dict rows from
:func:`bookings.rebook_rate_export.export_rebook_rate_rows`
-- the same rows the CSV is built from -- as JSON via
``DjangoJSONEncoder``. Output is written unchanged, to
``--output`` when given and to stdout otherwise. An unknown
format raises ``CommandError``. Backend only; read-only.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from bookings.rebook_rate_export import (
    export_rebook_rate_csv,
    export_rebook_rate_rows,
)
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD.") from exc


class Command(BaseCommand):
    help = "Export one salon's rebook rate summary as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--date-from", "--from-date", "--start-date",
                            dest="date_from", type=_parse_date, default=None,
                            help="Inclusive first day, YYYY-MM-DD.")
        parser.add_argument("--date-to", "--to-date", "--end-date",
                            dest="date_to", type=_parse_date, default=None,
                            help="Inclusive last day, YYYY-MM-DD.")
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
                f"No salon with id {options['salon_id']}.") from exc
        if options.get("date_from") is None:
            raise CommandError("A --date-from is required.")
        try:
            if fmt == "json":
                text = json.dumps(
                    export_rebook_rate_rows(
                        salon, options["date_from"], options.get("date_to")),
                    indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_rebook_rate_csv(
                    salon, options["date_from"], options.get("date_to"))
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
