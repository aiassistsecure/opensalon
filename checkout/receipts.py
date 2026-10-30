"""Receipt issuing and emailing for checkout.

A receipt is a snapshot: :func:`build_receipt` copies the sale's
lines, total and tender at issue time into a ``Receipt`` so later
edits never rewrite what the client was given.

Email goes through Django's standard mail settings only
(``django.core.mail``): a salon points ``EMAIL_HOST`` /
``EMAIL_PORT`` / ``EMAIL_HOST_USER`` / ``EMAIL_HOST_PASSWORD`` /
``EMAIL_USE_TLS`` and ``DEFAULT_FROM_EMAIL`` at its own mail server
(for example its own SMTP server) in settings/environment. Core
uses no vendor email API and no payment-provider SDK or field.
"""
from django.core.mail import send_mail
from django.utils import timezone

from .models import Receipt


def build_receipt(sale):
    """Create (or return the existing) receipt snapshot for ``sale``."""
    receipt, _created = Receipt.objects.get_or_create(
        sale=sale,
        defaults={
            "salon_name": str(sale.salon) if sale.salon_id else "",
            "lines": [
                {
                    "description": item.description or item.get_kind_display(),
                    "kind": item.kind,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "line_total": str(item.line_total),
                }
                for item in sale.items.all()
            ],
            "total": sale.total,
            "tender": [
                {
                    "method": payment.method,
                    "amount": str(payment.amount),
                    "status": payment.status,
                }
                for payment in sale.payments.all()
            ],
        },
    )
    return receipt


def render_receipt_text(receipt):
    """Plain-text receipt body (also used as the email body)."""
    lines = [receipt.salon_name or "Receipt", f"Sale #{receipt.sale_id}", ""]
    for line in receipt.lines:
        lines.append(
            f"{line['description']} x{line['quantity']} — {line['line_total']}"
        )
    lines.append("")
    lines.append(f"Total: {receipt.total}")
    for tender in receipt.tender:
        lines.append(f"Paid ({tender['method']}): {tender['amount']}")
    lines.append("")
    lines.append("Thank you.")
    return "\n".join(lines)


def send_receipt(receipt, recipient=None):
    """Email ``receipt`` via Django mail; returns the receipt.

    Recipient defaults to the sale's client email. Raises ValueError
    when no recipient is available. On success records
    ``recipient_email`` and ``sent_at`` on the receipt.
    """
    sale = receipt.sale
    recipient = recipient or (sale.client.email if sale.client_id else "")
    if not recipient:
        raise ValueError("no recipient email for receipt")
    sent = send_mail(
        subject=f"Your receipt from {receipt.salon_name or 'your salon'}",
        message=render_receipt_text(receipt),
        from_email=None,  # Django uses DEFAULT_FROM_EMAIL
        recipient_list=[recipient],
    )
    if sent:
        receipt.recipient_email = recipient
        receipt.sent_at = timezone.now()
        receipt.save(update_fields=["recipient_email", "sent_at"])
    return receipt
