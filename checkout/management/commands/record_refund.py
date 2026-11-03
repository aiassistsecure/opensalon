"""Record a refund against a completed sale.

Usage:
    python manage.py record_refund --sale-id ID --amount AMOUNT
        [--reason TEXT] [--tender TENDER] [--dry-run]

With ``--dry-run`` nothing is written: the command calls the
service's validate-only helper (no write happens at all, so
the preview is safe on every backend -- NEDB does not roll
back transaction writes), so the preview applies the
service's own refusals and prints the refund that WOULD be
recorded (amount, tender, resulting refund total).

Thin wrapper around :func:`checkout.refunds.record_refund`:
the sale is resolved by id and all other arguments are passed
to the service verbatim -- its refusals (e.g. a refund on a
non-completed sale, an over-refund, or a tender that does not
match an original payment) stay the single source of truth and
surface here as ``CommandError``. Core stays provider-agnostic
-- no payment-provider SDK, field, or name appears here.
"""
from django.core.management.base import BaseCommand, CommandError

from checkout.models import Sale
from checkout.refunds import (
    record_refund, refund_total, validate_record_refund)


class Command(BaseCommand):
    help = "Record a refund against a completed sale."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sale-id", type=int, required=True,
            help="Id of the completed sale to refund.",
        )
        parser.add_argument(
            "--amount", required=True,
            help="Refund amount (must be positive).",
        )
        parser.add_argument(
            "--reason", default="",
            help="Optional reason stored on the refund.",
        )
        parser.add_argument(
            "--tender", default=None,
            help="Core tender for the refund (default: the "
                 "service's default -- the sale's sole payment "
                 "tender, or cash when it has no payments).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview only: print the refund that would be "
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
                amount, tender = validate_record_refund(
                    sale, options["amount"],
                    reason=options["reason"] or "",
                    tender=options.get("tender"))
                resulting_total = refund_total(sale) + amount
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(
                f"Dry run: would record refund of {amount} "
                f"({tender}) against sale #{sale.pk}: refund "
                f"total would be {resulting_total}; no refund "
                f"recorded.")
            return
        try:
            refund = record_refund(
                sale, options["amount"],
                reason=options["reason"] or "",
                tender=options.get("tender"))
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Recorded refund #{refund.pk} of {refund.amount} "
            f"({refund.tender}) against sale #{sale.pk}: refund "
            f"total {refund_total(sale)}.")
