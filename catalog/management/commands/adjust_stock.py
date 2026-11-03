"""Manually adjust one product's stock via the catalog adjust service.

Usage:
    python manage.py adjust_stock --salon-id ID --product-id ID
        --delta N --reason TEXT [--dry-run]

With ``--dry-run`` nothing is recorded: the command runs the
service inside a transaction it rolls back, and prints a preview
of the ``StockMovement`` that would be recorded — its kind, signed
delta, and reason — together with the on-hand quantity that would
result.

Backend only — no views, templates, or UI. This command is a thin
wrapper around :func:`catalog.adjust.adjust_stock`: it resolves
the salon by id and the product within that salon, delegates to
that service verbatim, and prints a one-line summary. It adds no
adjustment, validation, or stock logic of its own — movements
remain the one source of truth and the service alone decides what
is recordable — so the printed result and the recorded movement
can never disagree.

Semantics are the service's own: ``--delta`` is a signed non-zero
integer, ``--reason`` is required and is stored verbatim as the
movement's note, and an adjustment may never drive stock below
zero. A blank or over-long reason, a zero delta, or a
below-zero result raises the service's ``ValueError``, surfaced
here as ``CommandError``; an unknown salon or a product outside
that salon is also a ``CommandError``.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from catalog.adjust import adjust_stock
from catalog.models import Product
from saloncore.models import Salon


class Command(BaseCommand):
    help = "Manually adjust a product's stock by a signed amount."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon-id", required=True, type=int,
            help="ID of the salon owning the product.",
        )
        parser.add_argument(
            "--product-id", required=True, type=int,
            help="ID of the product of this salon to adjust.",
        )
        parser.add_argument(
            "--delta", required=True, type=int,
            help="Signed quantity to adjust by (non-zero).",
        )
        parser.add_argument(
            "--reason", required=True,
            help="Why the stock is being adjusted; stored verbatim "
                 "as the movement's note.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview the movement that would be recorded "
                 "without recording anything.",
        )

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
                f"No product with id {options['product_id']} in "
                f"salon {salon.pk}.") from exc
        delta = options["delta"]
        reason = options["reason"]
        if options.get("dry_run"):
            try:
                with transaction.atomic():
                    new_stock = adjust_stock(product, delta, reason)
                    transaction.set_rollback(True)
            except (TypeError, ValueError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                f"Dry run: would record adjustment movement "
                f"{delta:+d} x {product.name} (product {product.pk}) "
                f"for {reason.strip()!r}: resulting stock "
                f"{new_stock}.")
            return
        try:
            new_stock = adjust_stock(product, delta, reason)
        except (TypeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Adjusted {delta:+d} x {product.name} "
            f"(product {product.pk}) for {reason.strip()!r}: "
            f"current stock {new_stock}.")
