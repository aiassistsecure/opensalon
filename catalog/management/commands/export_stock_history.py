"""Export one product's stock history as CSV via the history export service.

Usage:
    python manage.py export_stock_history --salon-id ID
        [--product-id PRODUCT_ID] [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around
:func:`catalog.history_export.export_stock_history_csv`:
it resolves the salon by id, delegates to that service verbatim
(with the same optional ``product``), and writes the returned CSV
to ``--output`` when given, otherwise to stdout. It adds no fields,
filtering, or export logic of its own, so the command output and
the service output can never disagree — one source of truth.

Product semantics are the service's own: ``--product-id`` names a
product of this salon by id (the service also accepts a saved
Product instance from programmatic callers); a foreign or unknown
product raises the service's ``ValueError``, surfaced here as
``CommandError``. With no product at all the service requires one,
which likewise surfaces as ``CommandError``.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
from django.core.management.base import BaseCommand, CommandError

from catalog.history_export import export_stock_history_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export one product's stock history as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose stock history to export.",
        )
        parser.add_argument(
            "--product-id", "--product", dest="product_id",
            default=None, type=int,
            help="ID of the product of this salon whose stock "
                 "history to export (default: none, which the "
                 "service rejects as requiring a product).",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        # Programmatic callers may pass product= a Product/id instead.
        product = options.get("product_id")
        if product is None and options.get("product") is not None:
            product = options["product"]
        try:
            text = export_stock_history_csv(salon, product)
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
