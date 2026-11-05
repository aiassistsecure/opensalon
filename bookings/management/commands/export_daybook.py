"""Export one salon's day book for one day as CSV or JSON.

Usage:
    python manage.py export_daybook --salon-id ID --date YYYY-MM-DD
        [--format json|csv] [--output PATH]

Thin wrapper around :mod:`bookings.daybook_export`: the
salon is resolved by id, the date is parsed to a
``datetime.date``, and both are passed to the service verbatim
-- its CSV text is written unchanged, to ``--output`` when
given and to stdout otherwise. For ``--format csv`` (the
default) that CSV output is exactly as before, byte-identical;
for ``--format json`` the same arguments are passed to the dict
service :func:`bookings.daybook_export.export_daybook` (beside
its CSV twin) and its rows are serialised as JSON, so the two
formats can never disagree -- one source of truth. This command
adds no export logic of its own, so command and service output
can never disagree. Backend only; read-only.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from bookings.daybook_export import export_daybook, export_daybook_csv
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _coerce_date(value):
    if value is None or isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid date {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's day book for one day as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose day book to export.",
        )
        parser.add_argument(
            "--date", dest="date", type=_parse_date, required=True,
            help="Day to export, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the export to (default: stdout).",
        )

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
        day = _coerce_date(options.get("date"))
        if fmt == "json":
            rows = export_daybook(salon, day)
            text = json.dumps(rows, indent=2) + "\n"
        else:
            text = export_daybook_csv(salon, day)
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
