"""Re-send an existing receipt by email.

Usage:
    python manage.py resend_receipt --sale-id ID [--recipient EMAIL]
    python manage.py resend_receipt --receipt-id ID [--recipient EMAIL]

Thin wrapper around the existing services in
:mod:`checkout.receipt_resend`: ``--sale-id`` delegates verbatim
to :func:`checkout.receipt_resend.resend_receipt_for_sale` and
``--receipt-id`` delegates verbatim to
:func:`checkout.receipt_resend.resend_receipt`. Exactly one of
the two identifiers is required. The optional ``--recipient``
is passed through unchanged; when omitted the service applies
its own default (the receipt's stored recipient, falling back
to the sale's client email). This command adds no resend logic
of its own, so command and service behaviour can never
disagree -- one source of truth.

Invalid input -- neither or both identifiers, an unknown sale
or receipt, or a service refusal (for example a voided or
not-completed sale, or a sale with no existing receipt) --
raises ``CommandError`` and no email is sent in those cases.

Email goes through the service and Django's standard mail
settings only, exactly as the service defines them. Core stays
provider-agnostic -- no vendor email API, no payment-provider
SDK, field, or name appears here.
"""
from django.core.management.base import BaseCommand, CommandError

from checkout.models import Receipt, Sale
from checkout.receipt_resend import resend_receipt, resend_receipt_for_sale


class Command(BaseCommand):
    help = "Re-send an existing receipt by email."

    def add_arguments(self, parser):
        parser.add_argument(
            "--sale-id", type=int, default=None,
            help="Id of the sale whose existing receipt to re-send.",
        )
        parser.add_argument(
            "--receipt-id", type=int, default=None,
            help="Id of the existing receipt to re-send.",
        )
        parser.add_argument(
            "--recipient", "--email", dest="recipient", default=None,
            help="Recipient email address (default: the service's "
                 "default -- the receipt's stored recipient, "
                 "falling back to the sale's client email).",
        )

    def handle(self, *args, **options):
        sale_id = options.get("sale_id")
        receipt_id = options.get("receipt_id")
        recipient = options.get("recipient") or None
        if (sale_id is None) == (receipt_id is None):
            raise CommandError(
                "Provide exactly one of --sale-id or --receipt-id."
            )
        try:
            if sale_id is not None:
                try:
                    sale = Sale.objects.get(pk=sale_id)
                except Sale.DoesNotExist as exc:
                    raise CommandError(
                        f"No sale with id {sale_id}."
                    ) from exc
                receipt = resend_receipt_for_sale(sale, recipient=recipient)
            else:
                try:
                    receipt_obj = Receipt.objects.get(pk=receipt_id)
                except Receipt.DoesNotExist as exc:
                    raise CommandError(
                        f"No receipt with id {receipt_id}."
                    ) from exc
                receipt = resend_receipt(receipt_obj, recipient=recipient)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            f"Re-sent receipt #{receipt.pk} for sale "
            f"#{receipt.sale_id} to {receipt.recipient_email}."
        )
