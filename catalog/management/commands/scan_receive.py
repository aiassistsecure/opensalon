"""Receive stock for one scanned product via the catalog scanning service.

Usage:
    python manage.py scan_receive --salon-id ID --code CODE
        [--quantity N] [--dry-run] [--format text|json]

With ``--dry-run`` nothing is recorded: the command prints a
preview naming the resolved product, the movement that would be
recorded (kind and signed quantity), and the stock that would
result.

With ``--format json`` the command prints exactly one JSON object
to stdout carrying the same facts as the text line: the product
id, the code as given, the quantity, the resulting stock level,
the stock movement id (null on a dry run), and ``dry_run``.

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
import json

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
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the movement that would be recorded "
                 "without recording anything.",
        )
        parser.add_argument(
            "--format", choices=["text", "json"], default="text",
            help="Output format: text (default) or json.",
        )

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            result = scan_receive(
                salon, options["code"], quantity=options["quantity"],
                dry_run=options.get("dry_run", False))
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        if not result.found:
            raise CommandError(
                f"No product in salon {salon.pk} matches code "
                f"{options['code']!r}.")
        if (options.get("format") or "text") == "json":
            self.stdout.write(json.dumps({
                "product_id": result.product.pk,
                "code": options["code"],
                "quantity": result.movement.quantity_delta,
                "current_stock": result.current_stock,
                "movement_id": (
                    result.movement.pk if result.movement else None),
                "dry_run": bool(options.get("dry_run")),
            }))
            return
        if options.get("dry_run"):
            self.stdout.write(
                f"Dry run: would record {result.movement.kind} "
                f"movement {result.movement.quantity_delta:+d} x "
                f"{result.product.name} (product {result.product.pk}): "
                f"resulting stock {result.current_stock}.")
            return
        self.stdout.write(
            f"Received {result.movement.quantity_delta:+d} x "
            f"{result.product.name} (product {result.product.pk}): "
            f"current stock {result.current_stock}.")
