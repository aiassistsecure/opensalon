"""Export a salon's last-7-days revenue split as CSV or JSON.

Usage:
    python manage.py export_split --salon-id ID
        [--today YYYY-MM-DD] [--format json|csv] [--output PATH]

Thin wrapper around :mod:`insights.split_export` — that service
is the one source of truth for the revenue-split export; this
command only resolves the salon, delegates to it verbatim, and
writes what it returns (to ``--output`` when given, otherwise to
stdout). For ``--format csv`` (the default) it writes
:func:`insights.split_export.export_split_csv`'s CSV string,
exactly as before; for ``--format json`` it serialises the SAME
dict rows from :func:`insights.split_export.export_split` as
JSON. The ``--today`` filter composes with both formats exactly
as it does for CSV. ``--today`` defaults to ``None``, exactly as
the service defines it. This command adds no export logic of
its own, so command and service output can never disagree.

An unknown salon, an unparseable date, or an unknown format
raises ``CommandError``. Dates mean whole local days in the
salon's timezone, inclusive, exactly as the service defines
them. Read-only.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from insights.split_export import export_split, export_split_csv
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
            f"Invalid today {value!r}; expected YYYY-MM-DD."
        ) from exc


class Command(BaseCommand):
    help = "Export a salon's last-7-days revenue split as CSV (default) or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose revenue split to export.",
        )
        parser.add_argument(
            "--today", "--end-date", "--end", "--date-to", dest="today",
            default=None,
            help="Last day of the 7-day window, YYYY-MM-DD "
                 "(inclusive; default: the service's own default).",
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
        today = _parse_date(options["today"])
        try:
            if fmt == "json":
                rows = export_split(salon, today=today)
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_split_csv(salon, today=today)
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
