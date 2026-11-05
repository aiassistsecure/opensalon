"""Export a salon's busiest days by revenue as CSV or JSON.

Usage:
    python manage.py export_busiest_revenue --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--format json|csv] [--output PATH]

Thin wrapper around the existing
:mod:`insights.busiest_revenue_export` service: the salon is
resolved by id, the dates are parsed to ``datetime.date``
objects, and both are passed to the service verbatim — its
output is written unchanged, to ``--output`` when given and to
stdout otherwise. For ``--format csv`` (the default) it writes
:func:`insights.busiest_revenue_export.export_busiest_days_by_revenue_csv`'s
CSV string, exactly as before; for ``--format json`` it
serialises the SAME dict rows from
:func:`insights.busiest_revenue_export.export_busiest_days_by_revenue`
as JSON. The date-window filters compose with both formats
exactly as they do for CSV. This command adds no export logic
of its own, so command and service output can never disagree
— one source of truth.

An unknown salon, an unparseable date, an unknown format, or
a service error raises ``CommandError``. Dates mean whole
local days in the salon's timezone, inclusive at both ends,
exactly as the service defines them. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from insights.busiest_revenue_export import (
    export_busiest_days_by_revenue,
    export_busiest_days_by_revenue_csv,
)
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
        raise CommandError(
            f"Invalid {label} {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's busiest days by revenue as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose busiest days by revenue "
                 "to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            default=None, required=False,
            help="First day of the range, YYYY-MM-DD (inclusive).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None, required=False,
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
        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")
        if start_date is None or end_date is None:
            raise CommandError(
                "Both --start-date and --end-date are required."
            )
        try:
            if fmt == "json":
                rows = export_busiest_days_by_revenue(
                    salon, start_date, end_date
                )
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_busiest_days_by_revenue_csv(
                    salon, start_date, end_date
                )
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
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
