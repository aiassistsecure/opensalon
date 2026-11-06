"""Export one salon's per-stylist utilization as CSV or JSON.

Usage: python manage.py export_utilization --salon-id ID
    --date-from YYYY-MM-DD [--date-to YYYY-MM-DD]
    [--format json|csv] [--output PATH]

Thin wrapper around :mod:`bookings.utilization_export`: salon
resolved by id, dates parsed, service output written unchanged
to --output or stdout. For ``--format csv`` (the default) it
writes :func:`bookings.utilization_export.export_utilization_csv`'s
CSV string as-is, so the historical CSV output is
byte-identical; for ``--format json`` it serialises the same
dict rows from
:func:`bookings.utilization_export.export_utilization` -- the
same rows the CSV is built from -- as JSON via
``DjangoJSONEncoder``. Unknown salon, missing or unparseable
date, service error, or unknown format raises ``CommandError``.
Backend only; read-only.
"""
import argparse
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from bookings.utilization_export import (
    export_utilization,
    export_utilization_csv,
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
    if value is None or isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value))
    except ValueError as exc:
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export one salon's per-stylist utilization as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose utilization to export.",
        )
        parser.add_argument(
            "--date-from", "--from-date", "--start-date",
            dest="date_from", type=_parse_date, default=None,
            help="Inclusive first day of a range, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--date-to", "--to-date", "--end-date",
            dest="date_to", type=_parse_date, default=None,
            help="Inclusive last day of a range, YYYY-MM-DD.",
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
                f"Invalid format {fmt!r}; expected 'json' or 'csv'."
            )
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        date_from = _coerce_date(options.get("date_from"), "date-from")
        if date_from is None:
            raise CommandError("A --date-from is required.")
        date_to = _coerce_date(options.get("date_to"), "date-to")
        try:
            if fmt == "json":
                text = json.dumps(
                    export_utilization(salon, date_from, date_to),
                    indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_utilization_csv(salon, date_from, date_to)
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
