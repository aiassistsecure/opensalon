"""Export a salon's daily revenue trend as CSV or JSON.

Usage:
    python manage.py export_trend --salon-id ID
        [--days N] [--end-date YYYY-MM-DD] [--format json|csv]
        [--output PATH]

Thin wrapper around :mod:`insights.trend_export`: the salon
is resolved by id, ``--days`` and ``--end-date`` are passed to
the service verbatim. For ``--format csv`` (the default) it
writes :func:`insights.trend_export.export_trend_csv`'s CSV
string as-is, so the historical CSV output is byte-identical;
for ``--format json`` it serialises the same dict rows from
:func:`insights.trend_export.export_trend` -- the same rows
the CSV is built from -- as JSON via ``DjangoJSONEncoder``.
Output is written unchanged to ``--output`` or stdout.
``--days`` defaults to 14 and ``--end-date`` defaults to
``None``, exactly as the service defines them.

An unknown salon, an unparseable date, an invalid ``--days``
value, or an unknown format raises ``CommandError``. Dates
mean whole local days in the salon's timezone, inclusive,
exactly as the service defines them. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError
from django.core.serializers.json import DjangoJSONEncoder

from insights.trend_export import export_trend, export_trend_csv
from saloncore.models import Salon

_FORMATS = ("json", "csv")


def _parse_date(value):
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
            f"Invalid end date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _parse_days(value):
    if isinstance(value, bool):
        raise CommandError(f"Invalid days {value!r}; expected an integer.")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Invalid days {value!r}; expected an integer."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's daily revenue trend as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose revenue trend to export.",
        )
        parser.add_argument(
            "--days", type=int, default=14,
            help="Number of calendar days in the window "
                 "(default: %(default)s).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None,
            help="Last day of the window, YYYY-MM-DD (inclusive; "
                 "default: the service's own default).",
        )
        parser.add_argument(
            "--format", dest="format", default="csv", choices=_FORMATS,
            help="Export format: csv (default) or json.")
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
        days = _parse_days(options["days"])
        end_date = _parse_date(options["end_date"])
        try:
            if fmt == "json":
                text = json.dumps(
                    export_trend(salon, days=days, end_date=end_date),
                    indent=2, cls=DjangoJSONEncoder) + "\n"
            else:
                text = export_trend_csv(salon, days=days, end_date=end_date)
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
