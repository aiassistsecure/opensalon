"""Export a salon's receipts as JSON or CSV.

Usage:
    python manage.py export_receipt --salon-id ID
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--sale-id ID] [--format json|csv] [--output PATH]

Thin wrapper around the existing
:func:`checkout.receipt_export.export_receipts` service:
the salon is resolved by id, the dates are parsed to
``datetime.date`` objects, and both are passed to the service
verbatim -- its rows are rendered as JSON for
``--format json`` (the default; the service builds them to
be JSON-serializable, and JSON serialization of its result,
as in the ``export_clients`` command, is the rendering) or
as CSV for ``--format csv`` (the same rows written with
:data:`checkout.receipt_export.EXPORT_FIELDNAMES` as the
header, in that order). Output is written unchanged, to
``--output`` when given and to stdout otherwise. Both dates
are optional exactly as the service defines them, so
omitting them exports every receipt for the salon. This
command adds no export logic of its own -- no new service
logic and no field changes -- so command and service output
can never disagree -- one source of truth.

With ``--sale-id`` the export is narrowed to that one sale's
receipts: the sale is resolved by id within the salon, and
an unknown id or a sale from another salon is a
``CommandError``. The resolved sale is passed to the service
as its optional ``sale`` argument. Without ``--sale-id`` the
command exports the whole salon range, exactly as before.

Invalid input -- an unparseable date, a reversed range, or
an unknown format -- raises ``CommandError``, as do service
errors. Dates mean whole local days in the salon's timezone,
inclusive at both ends, exactly as the service defines them.
Read-only. Core stays provider-agnostic -- no
payment-provider SDK, field, or name appears here.
"""
import csv
import datetime
import io
import json

from django.core.management.base import BaseCommand, CommandError

from checkout.models import Sale
from checkout.receipt_export import EXPORT_FIELDNAMES, export_receipts
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
    help = "Export a salon's receipts as JSON or CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose receipts to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: unbounded).",
        )
        parser.add_argument(
            "--sale-id", type=int, default=None,
            help="Id of the sale (in the salon) whose receipts to "
                 "export (default: all sales in the range).",
        )
        parser.add_argument(
            "--format", dest="format", default="json", choices=_FORMATS,
            help="Export format: json (default) or csv.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the export to (default: stdout).",
        )

    def handle(self, *args, **options):
        fmt = options.get("format") or "json"
        if fmt not in _FORMATS:
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'json' or 'csv'.")
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from exc
        sale = None
        if options.get("sale_id") is not None:
            try:
                sale = Sale.objects.get(
                    pk=options["sale_id"], salon=salon
                )
            except Sale.DoesNotExist as exc:
                raise CommandError(
                    f"No sale with id {options['sale_id']} "
                    f"for salon {options['salon_id']}."
                ) from exc
        start = _parse_date(options["start_date"], "start date")
        end = _parse_date(options["end_date"], "end date")
        if start is not None and end is not None and end < start:
            raise CommandError(
                f"End date {end.isoformat()} is before start date "
                f"{start.isoformat()}."
            )
        try:
            rows = export_receipts(start, end, salon=salon, sale=sale)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if fmt == "csv":
            buffer = io.StringIO()
            writer = csv.DictWriter(
                buffer, fieldnames=EXPORT_FIELDNAMES,
                lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            text = buffer.getvalue()
        else:
            text = json.dumps(rows, indent=2) + "\n"
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8") as fh:
                    fh.write(text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(text, ending="")
