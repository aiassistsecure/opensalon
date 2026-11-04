"""Export a salon's sale items verbatim as CSV.

Usage:
    python manage.py export_sale_items --salon-id ID
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
        [--sale-id ID] [--kind KIND] [--output PATH]

Thin wrapper around
:func:`checkout.sale_item_export.export_sale_items_csv` -- the
salon is resolved by id, dates are parsed, and the service's
CSV is written unchanged to ``--output`` or stdout, so command
and service can never disagree. With no dates, every stored
sale item of the salon is exported. An unparseable date, a
reversed range, or an end date without a start raises
``CommandError``. Read-only; provider-agnostic -- no provider
reference is exported.

With ``--sale-id`` the export is narrowed to that one sale's
items: the sale is resolved by id within the salon (the
service scopes items through ``sale__salon``; here the sale
itself is resolved with ``salon=salon``), and an unknown id or
a sale from another salon is a ``CommandError``. The resolved
sale is passed to the service as its optional ``sale``
argument. Without ``--sale-id`` the command exports the whole
salon, exactly as before.

With ``--kind`` the export is narrowed to sale items whose
stored kind exactly matches it (the core ``SaleItem.Kind``
slugs only); it composes with the window and ``--sale-id``,
and is passed to the service as its optional ``kind``
argument. Without ``--kind`` the command exports every kind,
exactly as before.
"""
import datetime

from django.core.management.base import BaseCommand, CommandError

from checkout.models import Sale
from checkout.sale_item_export import export_sale_items_csv
from saloncore.models import Salon


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
    help = "Export a salon's sale items verbatim as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose sale items to export.",
        )
        parser.add_argument(
            "--start-date", "--start", "--date-from", dest="start_date",
            default=None,
            help="First day of the range, YYYY-MM-DD (inclusive; "
                 "default: no range, all sale items).",
        )
        parser.add_argument(
            "--end-date", "--end", "--date-to", dest="end_date",
            default=None,
            help="Last day of the range, YYYY-MM-DD (inclusive; "
                 "default: the start date, a single-day export).",
        )
        parser.add_argument(
            "--sale-id", type=int, default=None,
            help="Id of the sale (in the salon) whose sale items "
                 "to export (default: all sales).",
        )
        parser.add_argument(
            "--kind", dest="kind", default=None,
            help="Sale item kind value to filter by (default: "
                 "all kinds).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path to write the CSV to (default: stdout).",
        )

    def handle(self, *args, **options):
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
            text = export_sale_items_csv(
                salon, start, end, sale=sale,
                kind=options.get("kind"))
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
