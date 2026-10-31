"""Manual stock adjustment service for the catalog.

Backend only — no views, templates, or UI.

An adjustment is an explicit correction to a product's stock in
either direction (damaged goods written off, a found unit put back,
a receiving error corrected, ...). It is recorded as exactly one
``StockMovement`` of kind ``ADJUSTMENT`` carrying the signed
``delta`` and the caller's ``reason`` verbatim in its ``note``, so
the movement log stays the one source of truth and every correction
stays auditable with its reason attached.

Stock is derived, never stored: the quantity returned is
``Product.current_stock`` read *after* the movement is recorded —
the sum of all movement deltas, not a counter.

Unlike a scan sale (see :mod:`catalog.scanning`, which allows
sell-then-reconcile below zero), an adjustment may never drive
stock negative: if ``current + delta < 0`` the adjustment is
rejected with ``ValueError`` and no movement is recorded. Landing
exactly on zero is fine.
"""
from django.db import transaction

from catalog.models import Product, StockMovement


def _clean_product(product):
    if not isinstance(product, Product) or product.pk is None:
        raise ValueError("product must be a saved Product instance")
    return product


def _clean_delta(delta):
    if isinstance(delta, bool) or not isinstance(delta, int):
        raise ValueError("delta must be an integer")
    if delta == 0:
        raise ValueError("delta must be non-zero")
    return delta


def _clean_reason(reason):
    text = str(reason or "").strip()
    if not text:
        raise ValueError("a non-blank reason is required")
    if len(text) > 255:
        raise ValueError("reason is too long")
    return text


def adjust_stock(product, delta, reason):
    """Adjust ``product``'s stock by signed ``delta`` for ``reason``.

    Records one ``ADJUSTMENT`` movement (``quantity_delta=delta``,
    ``note=reason``) and returns the new on-hand quantity derived
    from the movement ledger after the movement lands.

    Raises ``ValueError`` — recording nothing — when the product is
    not a saved :class:`~catalog.models.Product`, ``delta`` is not a
    non-zero integer, ``reason`` is blank (or too long for the
    movement note), or the adjustment would drive the derived stock
    below zero.
    """
    product = _clean_product(product)
    delta = _clean_delta(delta)
    reason = _clean_reason(reason)
    with transaction.atomic():
        current = product.current_stock
        new_stock = current + delta
        if new_stock < 0:
            raise ValueError(
                f"adjustment of {delta:+d} would drive stock negative "
                f"({current} on hand)"
            )
        StockMovement.objects.create(
            product=product,
            kind=StockMovement.Kind.ADJUSTMENT,
            quantity_delta=delta,
            note=reason,
        )
        return product.current_stock
