"""Export a salon's service-category mix report as CSV or JSON.

Usage:
    python manage.py export_category_mix --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--format json|csv] [--output PATH]

Thin wrapper around
:mod:`insights.category_mix_export`: salon resolved by id,
dates parsed to ``datetime.date``, both passed verbatim. For
``--format csv`` (the default) it writes
:func:`insights.category_mix_export.export_category_mix_csv`'s
CSV string as-is, so the historical CSV output is
byte-identical; for ``--format json`` it serialises the same
dict rows from
:func:`insights.category_mix_export.export_category_mix` —
the same rows the CSV is built from — as JSON via
``DjangoJSONEncoder``. Output is written unchanged to
``--output`` or stdout. No export logic of its own (one source
of truth). Unknown salon, unparseable date, or service error
or unknown format raises ``CommandError``.
Dates are whole local days in the salon's timezone, inclusive.
Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from insights.category_mix_export import (
    export_category_mix,
    export_category_mix_csv,
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
    help = "Export a salon's service-category mix report as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--start-date", "--start", "--date-from",
                            dest="start_date", default=None,
                            help="First day, YYYY-MM-DD (inclusive).")
        parser.add_argument("--end-date", "--end", "--date-to",
                            dest="end_date", default=None,
                            help="Last day, YYYY-MM-DD (inclusive).")
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
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
        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")
        if start_date is None or end_date is None:
            raise CommandError(
                "Both --start-date and --end-date are required."
            )
        try:
            if fmt == "json":
                text = json.dumps(
                    export_category_mix(salon, start_date, end_date),
                    indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_category_mix_csv(salon, start_date, end_date)
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
