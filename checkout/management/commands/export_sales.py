"""Export a salon's sales verbatim as CSV or JSON.

Usage:
    python manage.py export_sales --salon-id ID
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--status STATUS] [--format json|csv] [--output PATH]

Thin wrapper around
:func:`checkout.sale_export.export_sales_csv` and
:func:`checkout.sale_export.export_sales` -- the salon is
resolved by id, dates are parsed, and the service's output is
written unchanged to ``--output`` or stdout, so command and
service can never disagree. For ``--format csv`` (the
default) the service's CSV is written exactly as before; for
``--format json`` the same dict rows from
:func:`checkout.sale_export.export_sales` are serialised as
JSON. With no dates, every stored sale of the salon is
exported. An unparseable date, a reversed range, an end date
without a start, or an unknown format raises
``CommandError``. Read-only; provider-agnostic -- no provider
reference is exported.
"""
import datetime
import json

from django.core.management.base import BaseCommand, CommandError

from checkout.sale_export import export_sales, export_sales_csv
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
    help = "Export a salon's sales verbatim as CSV or JSON."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose sales to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: no range, all sales).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: the start date, a single-day export).",
        )
        parser.add_argument(
            "--status", dest="status", default=None,
            help="Sale status value to filter by.",
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
        start = _parse_date(options["start_date"], "start date")
        end = _parse_date(options["end_date"], "end date")
        if start is None and end is not None:
            raise CommandError(
                "An end date requires a start date."
            )
        if end is not None and start is not None and end < start:
            raise CommandError(
                f"End date {end.isoformat()} is before start date "
                f"{start.isoformat()}."
            )
        try:
            if fmt == "json":
                rows = export_sales(
                    salon, start, end, status=options.get("status"))
                text = json.dumps(rows, indent=2) + "\n"
            else:
                text = export_sales_csv(
                    salon, start, end, status=options.get("status"))
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
