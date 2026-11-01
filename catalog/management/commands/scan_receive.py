"""Receive stock for one scanned product via the catalog scanning service.

Usage:
    python manage.py scan_receive --salon-id ID --code CODE
        [--quantity N]

Backend only — no views, templates, or UI. This command is a thin
wrapper around :func:`catalog.scanning.scan_receive`: it resolves
the salon by id, delegates to that service verbatim, and prints a
one-line summary built only from fields on the returned
``ScanResult``. The service never raises for an unknown or blank
code — it returns ``ScanResult(found=False)`` and records nothing —
so the command surfaces that documented not-found outcome as a
``CommandError``, as it does for the service's ``ValueError`` on a
non-positive quantity. Stock stays derived from movements only:
the service appends the movement; this command adds nothing of
its own.
"""
from django.core.management.base import BaseCommand, CommandError

from catalog.scanning import scan_receive
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Receive stock for a product scanned by barcode or SKU."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon receiving the stock.",
        )
        parser.add_argument(
            "--code", required=True,
            help="Barcode or SKU delivered by the scanner.",
        )
        parser.add_argument(
            "--quantity", type=int, default=1,
            help="Units to receive (default: 1).",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            result = scan_receive(
                salon, options["code"], quantity=options["quantity"])
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if not result.found:
            raise CommandError(
                f"No product in salon {salon.pk} matches code "
                f"{options['code']!r}.")
        self.stdout.write(
            f"Received {result.movement.quantity_delta:+d} x "
            f"{result.product.name} (product {result.product.pk}): "
            f"current stock {result.current_stock}.")
