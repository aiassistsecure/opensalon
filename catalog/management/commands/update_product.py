"""Update one catalog product via the catalog update_product service.

Usage:
    python manage.py update_product --salon-id ID --product-id ID
        [--name TEXT] [--price AMOUNT] [--sku CODE]
        [--barcode CODE] [--active | --inactive] [--dry-run]

Every field flag is optional: an omitted flag leaves that field
unchanged (the service's ``None`` sentinel), and giving no field
at all is refused. Stock is not updatable here — ``StockMovement``
rows own stock — and ``external_id``/``payload`` are immutable
source identity, so neither is offered.

With ``--dry-run`` nothing is written: the command calls ONLY
the service's read-only ``validate_update_product`` helper and
prints the fields that WOULD change. The writer is never called
and no rollback is relied on, so the preview is safe on every
backend (including NEDB, where a rolled-back transaction does
not undo writes).

Backend only — no views, templates, or UI. This command is a
thin wrapper around :func:`catalog.update_product.update_product`:
it resolves the salon and the product (scoped to that salon),
delegates to that service verbatim, and prints a one-line
summary. It adds no validation or barcode-uniqueness logic of
its own — the service alone is the single source of truth.

An unknown salon/product or a service ``ValueError``
(blank/over-long name, over-long SKU/barcode, bad or negative
price, duplicate barcode, no fields given) is surfaced here as
``CommandError``.
"""
from django.core.management.base import BaseCommand, CommandError

from catalog.models import Product
from catalog.update_product import update_product, validate_update_product
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Update one catalog product in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the product.")
        parser.add_argument(
            "--product-id", required=True, type=int,
            help="ID of the product to update.")
        parser.add_argument(
            "--name", default=None,
            help="New product name; omitted = unchanged.")
        parser.add_argument(
            "--price", default=None,
            help="New retail price (e.g. 24.00); omitted = unchanged.")
        parser.add_argument(
            "--sku", default=None,
            help="New SKU code; omitted = unchanged.")
        parser.add_argument(
            "--barcode", default=None,
            help="New barcode, unique in the salon; "
                 "omitted = unchanged.")
        parser.add_argument(
            "--active", action="store_true", default=None,
            help="Set the product active.")
        parser.add_argument(
            "--inactive", action="store_true", default=None,
            help="Set the product inactive.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the update that would apply "
                 "without writing anything.")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        try:
            product = Product.objects.get(
                pk=options["product_id"], salon=salon)
        except Product.DoesNotExist as exc:
            raise CommandError(
                f"No product with id {options['product_id']} "
                f"in salon {salon.pk}.") from exc
        # call_command may pass active= directly; CLI uses the flags.
        if options.get("active") is not None and options.get("inactive"):
            raise CommandError("Pass --active or --inactive, not both.")
        if options.get("inactive"):
            active = False
        elif options.get("active") is not None:
            active = bool(options["active"])
        else:
            active = None
        kwargs = dict(
            name=options.get("name"), price=options.get("price"),
            sku=options.get("sku"), barcode=options.get("barcode"),
            active=active)
        if all(value is None for value in kwargs.values()):
            raise CommandError(
                "At least one field must be given: --name, --price, "
                "--sku, --barcode, --active, or --inactive.")
        if options.get("dry_run"):
            try:
                cleaned = validate_update_product(
                    salon, product, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            shown = ", ".join(
                f"{field}={cleaned[field]!r}"
                for field in ("name", "price", "sku", "barcode", "active")
                if field in cleaned)
            self.stdout.write(
                f"Dry run: would update product {product.pk} "
                f"in salon {salon.pk}: {shown} "
                f"-- no product written.")
            return
        try:
            product = update_product(salon, product, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Updated product {product.pk}: {product.name!r} "
            f"in salon {salon.pk}: sku={product.sku!r} "
            f"barcode={product.barcode!r} price={product.price} "
            f"active={product.active}.")
