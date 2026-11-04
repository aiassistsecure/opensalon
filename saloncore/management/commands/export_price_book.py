"""Export a salon's full price book as CSV.

Usage:
    python manage.py export_price_book --salon-id ID
        [--service-id ID] [--output PATH]

Thin wrapper around :func:`saloncore.price_book_export.export_price_book_csv`
-- that service is the one source of truth for the price book
export; this command only resolves the salon, delegates to it
verbatim, and writes the CSV it returns (to ``--output`` when
given, otherwise to stdout). Backend only; read-only.

With ``--service-id`` the export is narrowed to that one
service's rows: the service is resolved by id within the
salon (via its category's salon, the app's service scoping
convention; a service from another salon, or an unknown id, is
a ``CommandError``), and the resolved service is passed to the
service as its optional ``service`` argument. Without
``--service-id`` the command exports the whole salon, exactly
as before.
"""
from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, Service
from saloncore.price_book_export import export_price_book_csv


class Command(BaseCommand):
    help = "Export a salon's full price book as CSV."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", type=int, required=True,
            help="Id of the salon whose price book to export.",
        )
        parser.add_argument(
            "--service-id", type=int, default=None,
            help="Id of the service (in the salon) whose price "
                 "book rows to export (default: all services).",
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
        service = None
        if options.get("service_id") is not None:
            try:
                service = Service.objects.get(
                    pk=options["service_id"], category__salon=salon)
            except Service.DoesNotExist:
                raise CommandError(
                    f"No service with id {options['service_id']} "
                    f"for salon {options['salon_id']}."
                ) from None
        csv_text = export_price_book_csv(salon, service=service)
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
