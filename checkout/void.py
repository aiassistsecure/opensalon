"""Void-sale service for checkout.

Backend only — no views, templates, or UI.

:func:`void_sale` marks a completed sale voided, recording why
(``void_reason``) and when (``voided_at``) on the sale itself —
the sale is the one source of truth for its own state. Voiding
never deletes anything: the sale, its items, and its payments
stay on record, so the void itself remains auditable and the
original sale can still be inspected.

Voided sales are excluded from reporting: the existing
:func:`checkout.summary.daily_sales_summary` and
:func:`checkout.tender_totals.tender_totals` services already
filter out ``Sale.Status.VOIDED`` (asserted in
``checkout.test_void`` against sales voided through this
service).

Only a completed sale can be voided: an open sale was never
settled (abandon or correct it instead), and an already-voided
sale cannot be voided again — re-voiding would overwrite the
original reason and timestamp. A non-empty reason is required,
so no sale is ever voided without an explanation on record.

Core stays provider-agnostic: voiding touches no payment,
provider, field, or SDK — settling or reversing money with any
external provider is an adapter concern outside core.
"""
from django.utils import timezone

from .models import Sale


def void_sale(sale, reason):
    """Void the completed ``sale`` for ``reason`` and return it.

    Sets ``status`` to ``Sale.Status.VOIDED``, stores the
    stripped ``reason`` in ``void_reason``, stamps ``voided_at``
    with the current time, saves those fields, and returns the
    same (updated) sale instance.

    Raises ``ValueError`` if ``sale`` is ``None``, if ``reason``
    is empty or blank, if the sale is already voided, or if the
    sale is not completed.
    """
    if sale is None:
        raise ValueError("void_sale needs a sale")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("void_sale needs a non-empty reason")
    if sale.status == Sale.Status.VOIDED:
        raise ValueError("sale is already voided")
    if sale.status != Sale.Status.COMPLETED:
        raise ValueError("only a completed sale can be voided")
    sale.status = Sale.Status.VOIDED
    sale.void_reason = reason.strip()
    sale.voided_at = timezone.now()
    sale.save(update_fields=["status", "void_reason", "voided_at"])
    return sale
