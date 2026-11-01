"""Export a salon's per-product sales + stock turns as CSV.

Usage:
    python manage.py export_product_sales --salon-id ID [--output PATH]

Backend only — no views, templates, or UI. This command is a thin
wrapper around
:func:`catalog.product_sales_export.export_product_sales_csv`:
it resolves the salon by id, delegates to that service verbatim,
and writes the returned CSV to ``--output`` when given, otherwise
to stdout. It adds no fields, filtering, or formatting of its own,
so the command output and the service output can never disagree
— one source of truth.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.
"""
from django.core.management.base import BaseCommand, CommandError

from catalog.product_sales_export import export_product_sales_csv
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Export a salon's per-product sales and stock turns as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon whose product sales to export.",
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
        text = export_product_sales_csv(salon)
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
