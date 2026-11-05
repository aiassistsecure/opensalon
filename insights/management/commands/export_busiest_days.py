"""Export a salon's busiest days as CSV or JSON.

Usage:
    python manage.py export_busiest_days --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--format json|csv] [--output PATH]

Thin wrapper around :mod:`insights.busiest_export` — that
service is the one source of truth for the busiest-days export;
this command only resolves the salon, parses the dates to
``datetime.date`` objects, delegates to it verbatim, and writes
what it returns (to ``--output`` when given, otherwise to
stdout). For ``--format csv`` (the default) it writes
:func:`insights.busiest_export.export_busiest_days_csv`'s CSV
string, exactly as before; for ``--format json`` it serialises
the SAME dict rows from
:func:`insights.busiest_export.export_busiest_days` as JSON.
The date-window filters compose with both formats exactly as
they do for CSV. The service takes no extra keyword arguments,
so this command exposes none. This command adds no export
logic of its own, so command and service output can never
disagree.

An unknown salon, an unparseable date, or an unknown format
raises ``CommandError``. A reversed range behaves exactly as
the service defines it (seven zeroed weekday rows). Dates
mean whole local days in the salon's timezone, inclusive at
both ends, exactly as the service defines them. Read-only.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from insights.busiest_export import (
    export_busiest_days,
    export_busiest_days_csv,
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


class Command(BaseCommand):
    help = "Export a salon's busiest days as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose busiest days to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            type=_parse_date, required=True,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            type=_parse_date, required=True,
            help="Last day of the range, YYYY-MM-DD (inclusive).",
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
        if fmt == "json":
            rows = export_busiest_days(
                salon, options["start_date"], options["end_date"]
            )
            text = json.dumps(rows, indent=2) + "\n"
        else:
            text = export_busiest_days_csv(
                salon, options["start_date"], options["end_date"]
            )
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
