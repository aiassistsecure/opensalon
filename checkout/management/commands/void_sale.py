"""Void a completed sale.

Usage:
    python manage.py void_sale --sale-id ID --reason TEXT
        [--dry-run]

With ``--dry-run`` nothing is written: the command calls the
service's validate-only helper (no write happens at all, so
the preview is safe on every backend -- NEDB does not roll
back transaction writes), so the preview applies the
service's own refusals and prints the void that WOULD be
recorded (the sale, its reason, and its resulting
status).

Thin wrapper around :func:`checkout.void.void_sale`: the sale
is resolved by id and the reason is passed to the service
verbatim -- its refusals (an empty reason, an already-voided
sale, or a sale that is not completed) stay the single source
of truth and surface here as ``CommandError``. Core stays
provider-agnostic -- no payment-provider SDK, field, or name
appears here.
"""
from django.core.management.base import BaseCommand, CommandError

from checkout.models import Sale
from checkout.void import validate_void_sale, void_sale


class Command(BaseCommand):
    help = "Void a completed sale."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sale-id", type=int, required=True,
            help="Id of the completed sale to void.",
        )
        parser.add_argument(
            "--reason", required=True,
            help="Reason for the void, stored on the sale.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: print the void that would be "
                 "recorded and write nothing.",
        )

    def handle(self, *args, **options):
        try:
            sale = Sale.objects.get(pk=options["sale_id"])
        except Sale.DoesNotExist as exc:
            raise CommandError(
                f"No sale with id {options['sale_id']}.") from exc
        if options.get("dry_run"):
            try:
                reason = validate_void_sale(sale, options["reason"])
                status = Sale.Status.VOIDED
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                f"Dry run: would void sale #{sale.pk} (reason: "
                f"{reason}): sale status would be {status}; "
                f"sale not voided.")
            return
        try:
            voided = void_sale(sale, options["reason"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Voided sale #{voided.pk} (reason: "
            f"{voided.void_reason}): sale status {voided.status}.")
