"""Refund recording service for checkout.

Backend only — no views, templates, or UI.

A refund is an append-only :class:`checkout.models.Refund` record
against a completed sale. Recording one never mutates the original
``Sale`` or its ``Payment`` rows: the settlement stays exactly as
taken, and the refund stands alongside it as its own auditable row.

Rules: only a completed sale can be refunded (a voided sale is
already reversed, and an open sale was never settled); the amount
must be positive; and cumulative refunds may not exceed the sale
total — partial refunds are fine and sum against that cap. The
refund's tender must be a core tender (``Payment.Method``) matching
a tender actually used on the sale's payments, when the sale has
payments on record.

Core stays provider-agnostic: this module names no provider, uses
no provider field or SDK, and moves no money — returning money
through any external arrangement is an adapter concern outside core.
"""
from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from .models import Payment, Refund, Sale


def refunds_for_sale(sale):
    """Return the refunds recorded against ``sale``, oldest first."""
    if sale is None:
        raise ValueError("refunds_for_sale needs a sale")
    return Refund.objects.filter(sale=sale).order_by("id")


def refund_total(sale):
    """Return the total already refunded against ``sale`` as a Decimal."""
    if sale is None:
        raise ValueError("refund_total needs a sale")
    total = Refund.objects.filter(sale=sale).aggregate(total=Sum("amount"))["total"]
    return Decimal(total).quantize(Decimal("0.01")) if total is not None else Decimal("0.00")


def record_refund(sale, amount, reason="", tender=None):
    """Record a refund against a completed ``sale`` and return it.

    ``tender`` defaults to the sale's sole payment tender when it
    has exactly one; otherwise pass it explicitly. Raises
    ``ValueError`` if the sale is missing, voided, or not completed,
    if ``amount`` is not positive, if cumulative refunds plus
    ``amount`` would exceed the sale total, or if ``tender`` is not
    a core tender matching an original payment tender.
    """
    if sale is None:
        raise ValueError("record_refund needs a sale")
    if sale.status == Sale.Status.VOIDED:
        raise ValueError("a voided sale cannot be refunded")
    if sale.status != Sale.Status.COMPLETED:
        raise ValueError("only a completed sale can be refunded")
    try:
        amount = Decimal(amount)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("refund amount must be a number") from None
    if amount <= 0:
        raise ValueError("refund amount must be positive")
    amount = amount.quantize(Decimal("0.01"))
    original_tenders = set(
        Payment.objects.filter(sale=sale).values_list("method", flat=True)
    )
    if tender is None:
        if len(original_tenders) == 1:
            tender = next(iter(original_tenders))
        elif not original_tenders:
            tender = Payment.Method.CASH
        else:
            raise ValueError("refund needs a tender matching an original payment")
    if tender not in dict(Payment.Method.choices):
        raise ValueError("refund tender is not a core tender")
    if original_tenders and tender not in original_tenders:
        raise ValueError("refund tender must match an original payment tender")
    remaining = sale.total - refund_total(sale)
    if amount > remaining:
        raise ValueError("refund exceeds the sale total minus prior refunds")
    return Refund.objects.create(
        sale=sale,
        amount=amount,
        reason=reason.strip() if isinstance(reason, str) else "",
        tender=tender,
    )
