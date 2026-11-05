"""Export a salon's retail attach rate report as CSV or JSON.

Usage:
    python manage.py export_attach_rate --salon-id ID
        --start-date YYYY-MM-DD --end-date YYYY-MM-DD
        [--format json|csv] [--output PATH]
    python manage.py export_attach_rate --salon-id ID
        [--days N] [--end-date YYYY-MM-DD]
        [--format json|csv] [--output PATH]

Thin wrapper around :mod:`insights.attach_export`: salon
resolved by id, window passed verbatim. For ``--format csv``
(the default) it writes
:func:`insights.attach_export.export_attach_rate_csv`'s CSV
string, exactly as before; for ``--format json`` it serialises
the SAME single dict row from
:func:`insights.attach_export.export_attach_rate_row` as a
one-element JSON list via ``DjangoJSONEncoder``, so the two
formats can never disagree. Output is written unchanged to
``--output`` or stdout. No export logic of its own (one
source of truth). The start/end window mirrors
``export_category_mix``: it is translated only to the service's
own ``days``/``end_date`` window (days = inclusive day count),
never re-deriving any attach figure. Unknown salon, missing /
unparseable / reversed dates, conflicting or invalid ``--days``,
or a service error or unknown format raises ``CommandError``.
Dates are whole local days in the salon's timezone, inclusive.
Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from insights.attach_export import (
    export_attach_rate_csv,
    export_attach_rate_row,
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


def _parse_days(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise CommandError(f"Invalid days {value!r}; expected an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid days {value!r}; expected an integer."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's retail attach rate report as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument("--salon-id", type=int, required=True,
                            help="Id of the salon to export.")
        parser.add_argument("--start-date", "--start", "--date-from",
                            dest="start_date", default=None,
                            help="First day, YYYY-MM-DD (inclusive).")
        parser.add_argument("--end-date", "--end", "--date-to",
                            dest="end_date", default=None,
                            help="Last day, YYYY-MM-DD (inclusive).")
        parser.add_argument("--days", type=int, default=None,
                            help="Window length in days, ending on "
                                 "--end-date (alternative to --start-date).")
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
                f"No salon with id {options['salon_id']}."
            ) from exc
        start_date = _parse_date(options.get("start_date"), "start date")
        end_date = _parse_date(options.get("end_date"), "end date")
        days = _parse_days(options.get("days"))
        if start_date is not None:
            if end_date is None:
                raise CommandError(
                    "Both --start-date and --end-date are required."
                )
            if end_date < start_date:
                raise CommandError(
                    "End date must not be before start date."
                )
            derived = (end_date - start_date).days + 1
            if days is not None and days != derived:
                raise CommandError(
                    "--days conflicts with the --start-date/--end-date window."
                )
            days = derived
        elif days is None:
            raise CommandError(
                "Both --start-date and --end-date are required."
            )
        try:
            if fmt == "json":
                row = export_attach_rate_row(
                    salon, days=days, end_date=end_date)
                text = json.dumps(
                    [row], indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_attach_rate_csv(
                    salon, days=days, end_date=end_date)
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
