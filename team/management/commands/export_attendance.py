"""Export one salon's attendance summary as CSV or JSON.

Usage:
    python manage.py export_attendance --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--format json|csv] [--output PATH]

Thin wrapper around the existing
:mod:`team.attendance_export` services: for ``--format csv``
(the default) it delegates verbatim to
:func:`team.attendance_export.export_attendance_summary_csv`
-- the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and all three are passed to the
service verbatim -- its CSV text is written unchanged, to
``--output`` when given and to stdout otherwise. For
``--format json`` it serialises the SAME dict rows from
:func:`team.attendance_export.export_attendance_summary`
with the same arguments, so the two formats can never
disagree -- one source of truth. This command adds no
export logic of its own.

Every filter composes with both formats. An unknown
``--format`` raises ``CommandError`` (argparse ``choices``
reject it on the CLI; the explicit check covers
``call_command`` kwargs).

Invalid input -- an unknown salon, an unparseable date, or a
reversed range -- raises ``CommandError``. Dates mean whole
local days in the salon's timezone, inclusive at both ends,
exactly as the service defines them. Backend only -- no
views, templates, or UI. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.attendance_export import (
    export_attendance_summary,
    export_attendance_summary_csv,
)

_FORMATS = ("json", "csv")


def _parse_date(value, label):
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
    help = "Export one salon's attendance summary as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="Id of the salon whose attendance to export.")
        parser.add_argument(
            "--start-date", dest="start_date", required=True,
            help="First day of the range, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--end-date", dest="end_date", required=True,
            help="Last day of the range, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
        parser.add_argument(
            "--output", default=None,
            help="Path of the export file to write (default: stdout).")

    def handle(self, *args, **options):
        fmt = options.get("format") or "csv"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from None

        start = _parse_date(options["start_date"], "start date")
        end = _parse_date(options["end_date"], "end date")
        try:
            if fmt == "json":
                rows = export_attendance_summary(salon, start, end)
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_attendance_summary_csv(salon, start, end)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8",
                          newline="") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: "
                    f"{exc}") from exc
        else:
            self.stdout.write(text, ending="")
