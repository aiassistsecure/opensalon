"""Create one catalog product via the catalog add_product service.

Usage:
    python manage.py add_product --salon-id ID --name TEXT
        --price AMOUNT [--sku CODE] [--barcode CODE] [--inactive]
        [--dry-run]

With ``--dry-run`` nothing is written: the command calls the
service's read-only ``validate_add_product`` helper and prints
the product that WOULD be created — its name, SKU, barcode,
price, and active flag in the salon's scope. The writer is
never called, so the preview is safe on every backend
(including NEDB, where a rolled-back transaction does not
undo writes).

Backend only — no views, templates, or UI. This command is a
thin wrapper around :func:`catalog.add_product.add_product`: it
resolves the salon by id, delegates to that service verbatim,
and prints a one-line summary. It adds no creation, validation,
or barcode-uniqueness logic of its own — the service alone is
the single source of truth (including its refusal of a barcode
already used by another product in the same salon) — so the
printed result and the created product can never disagree.

An unknown salon or a service ``ValueError`` (blank/over-long
name, over-long SKU/barcode, bad or negative price, duplicate
barcode) is surfaced here as ``CommandError``.
"""
from django.core.management.base import BaseCommand, CommandError

from catalog.add_product import add_product, validate_add_product
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Create one catalog product in a salon."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the product.")
        parser.add_argument(
            "--name", required=True,
            help="Product name.")
        parser.add_argument(
            "--price", required=True,
            help="Retail price (e.g. 24.00).")
        parser.add_argument(
            "--sku", default="",
            help="Optional SKU code.")
        parser.add_argument(
            "--barcode", default="",
            help="Optional barcode; must be unique in the salon.")
        parser.add_argument(
            "--inactive", action="store_true",
            help="Create the product inactive (default: active).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the product that would be created "
                 "without writing anything.")

    def handle(self, *args, **options):
        try:
            salon = Salon.objects.get(pk=options["salon_id"])
        except Salon.DoesNotExist as exc:
            raise CommandError(
                f"No salon with id {options['salon_id']}.") from exc
        # call_command may pass active= directly; CLI uses --inactive.
        if options.get("active") is not None:
            active = bool(options["active"])
        else:
            active = not options.get("inactive", False)
        kwargs = dict(
            name=options["name"], price=options["price"],
            sku=options.get("sku") or "",
            barcode=options.get("barcode") or "", active=active)
        if options.get("dry_run"):
            try:
                cleaned = validate_add_product(salon, **kwargs)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            name = cleaned["name"]
            sku = cleaned["sku"]
            barcode = cleaned["barcode"]
            price = cleaned["price"]
            is_active = cleaned["active"]
            self.stdout.write(
                f"Dry run: would create product {name!r} "
                f"in salon {salon.pk}: sku={sku!r} "
                f"barcode={barcode!r} price={price} "
                f"active={is_active} -- no product written.")
            return
        try:
            product = add_product(salon, **kwargs)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Created product {product.pk}: {product.name!r} "
            f"in salon {salon.pk}: sku={product.sku!r} "
            f"barcode={product.barcode!r} price={product.price} "
            f"active={product.active}.")
