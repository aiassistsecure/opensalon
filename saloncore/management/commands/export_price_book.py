"""Export a salon's full price book as CSV.

Usage:
    python manage.py export_price_book --salon-id ID [--output PATH]

Thin wrapper around :func:`saloncore.price_book_export.export_price_book_csv`
-- that service is the one source of truth for the price book
export; this command only resolves the salon, delegates to it
verbatim, and writes the CSV it returns (to ``--output`` when
given, otherwise to stdout). Backend only; read-only.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from saloncore.price_book_export import export_price_book_csv


class Command(BaseCommand):
    help = "Export a salon's full price book as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose price book to export.",
        )
        parser.add_argument(
            "--output", default=None,
            help="Path of the CSV file to write (default: stdout).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist:
            raise CommandError(
                f"No salon with id {options['salon_id']}."
            ) from None
        csv_text = export_price_book_csv(salon)
        if options["output"]:
            try:
                with open(options["output"], "w", encoding="utf-8", newline="") as fh:
                    fh.write(csv_text)
            except OSError as exc:
                raise CommandError(
                    f"Cannot write export file {options['output']}: {exc}"
                ) from exc
        else:
            self.stdout.write(csv_text, ending="")
