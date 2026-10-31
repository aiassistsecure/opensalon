"""Re-send an existing receipt by email for checkout.

Backend only — no views, templates, or UI.

:func:`resend_receipt` sends a receipt that was already issued
(see :mod:`checkout.receipts`) again by email. It never creates
or rebuilds a receipt: the stored ``Receipt`` snapshot is what
is re-sent, so a re-send can never rewrite what the client was
originally given, even if the sale, its items, or the price
book have changed since.

Only a completed sale may have its receipt re-sent. A voided
sale's receipt must not go out again (the sale was reversed),
and an open sale was never settled, so its receipt — if one
was somehow built — is not a settled receipt to re-send.

Email goes through the existing :func:`checkout.receipts.send_receipt`,
which uses Django's standard mail settings only
(``django.core.mail``): a salon points ``EMAIL_HOST`` /
``EMAIL_PORT`` / ``EMAIL_HOST_USER`` / ``EMAIL_HOST_PASSWORD`` /
``EMAIL_USE_TLS`` and ``DEFAULT_FROM_EMAIL`` at its own mail
server (for example its own SMTP server) in settings/environment.
Core uses no vendor email API and no payment-provider SDK,
field, or assumption.
"""
from .models import Receipt, Sale
from .receipts import send_receipt


def resend_receipt(receipt, recipient=None):
    """Re-send the existing ``receipt`` by email; return the receipt.

    ``recipient`` defaults to the address the receipt was last
    sent to (``receipt.recipient_email``), falling back to the
    sale's client email via :func:`checkout.receipts.send_receipt`.
    On success ``send_receipt`` records the (possibly new)
    ``recipient_email`` and a fresh ``sent_at`` on the receipt.

    Raises ``ValueError`` if ``receipt`` is ``None``, if the
    receipt's sale is voided, or if the sale is not completed.
    No email is sent in any of those cases.
    """
    if receipt is None:
        raise ValueError("resend_receipt needs a receipt")
    sale = receipt.sale
    if sale.status == Sale.Status.VOIDED:
        raise ValueError("cannot re-send a receipt for a voided sale")
    if sale.status != Sale.Status.COMPLETED:
        raise ValueError("only a completed sale's receipt can be re-sent")
    return send_receipt(receipt, recipient=recipient or receipt.recipient_email or None)


def resend_receipt_for_sale(sale, recipient=None):
    """Re-send the existing receipt for ``sale``; return the receipt.

    Looks up the sale's already-issued receipt (the ``Receipt``
    one-to-one relation) and delegates to :func:`resend_receipt`.
    Raises ``ValueError`` if ``sale`` is ``None`` or the sale has
    no existing receipt — a re-send never builds a new one.
    """
    if sale is None:
        raise ValueError("resend_receipt_for_sale needs a sale")
    try:
        receipt = sale.receipt
    except Receipt.DoesNotExist:
        raise ValueError("sale has no existing receipt to re-send") from None
    return resend_receipt(receipt, recipient=recipient)
