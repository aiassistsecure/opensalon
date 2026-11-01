"""Backend sale service for checkout.

Backend only — no views, templates, or UI.

Until now the only code that could open, populate, and settle a
sale lived in the UI layer. This module is that flow's backend
home, so every surface (till, operator commands, scan-to-add)
shares one source of truth:

* :func:`create_sale` opens an ``OPEN`` sale for a salon, with an
  optional client of that same salon.
* :func:`add_service_item` / :func:`add_product_item` /
  :func:`add_series_item` append
  snapshot lines to an open sale. Prices and descriptions are
  copied onto the item at add time, so later price-book or
  catalogue changes never rewrite the sale. Money is ``Decimal``
  only — floats are rejected, never converted.
* :func:`complete_sale` settles an open sale through the existing
  provider-agnostic ``PaymentProvider`` interface
  (``checkout.payments``), records the ``Payment``, marks the sale
  completed, appends the ``StockMovement`` SALE delta for each
  product line, and builds the receipt via the existing
  ``checkout.receipts.build_receipt``.

Stock semantics mirror the catalogue: stock is never a counter —
it is derived from movements, and a product line's SALE movement
(delta ``-quantity``, note naming the sale) is appended only when
the sale actually completes. A failed charge therefore moves no
stock: it records a ``FAILED`` payment for audit, leaves the sale
``OPEN`` (so it can be retried or corrected), builds no receipt,
and raises ``ValueError``.

Core stays provider-agnostic: this module names no external
provider, uses no provider SDK or field, and maps a provider only
to a core tender (``Payment.Method``) via its ``name`` slug or an
explicit ``method`` argument.
"""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from catalog.models import StockMovement

from .models import Payment, Sale, SaleItem
from .receipts import build_receipt

_CENT = Decimal("0.01")


def _money(value, label):
    if isinstance(value, (bool, float)):
        raise ValueError(f"{label} must be a Decimal amount")
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} must be a Decimal amount") from None
    if amount < 0:
        raise ValueError(f"{label} must not be negative")
    return amount.quantize(_CENT)


def _quantity(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("quantity must be a positive integer")
    return value


def _require_open(sale):
    if sale is None:
        raise ValueError("a sale is required")
    if sale.status != Sale.Status.OPEN:
        raise ValueError("items and settlement need an open sale")
    return sale


def create_sale(salon, client=None):
    """Open a new sale for ``salon`` (optionally for ``client``)."""
    if salon is None:
        raise ValueError("create_sale needs a salon")
    if client is not None and client.salon_id != salon.pk:
        raise ValueError("client does not belong to the sale's salon")
    return Sale.objects.create(salon=salon, client=client)


def add_service_item(sale, unit_price, description="", service=None, quantity=1):
    """Append a service line to an open ``sale`` and return the item.

    ``description`` defaults to the linked service's name.
    """
    _require_open(sale)
    if service is not None:
        category = getattr(service, "category", None)
        if category is not None and category.salon_id != sale.salon_id:
            raise ValueError("service does not belong to the sale's salon")
        description = description or service.name
    return SaleItem.objects.create(
        sale=sale,
        kind=SaleItem.Kind.SERVICE,
        service=service,
        description=description or "",
        quantity=_quantity(quantity),
        unit_price=_money(unit_price, "unit_price"),
    )


def add_product_item(sale, product, quantity=1, unit_price=None):
    """Append a product line to an open ``sale`` and return the item.

    Price/description snapshot from ``product`` unless ``unit_price``
    is given. No stock moves yet: the SALE movement is appended by
    :func:`complete_sale`, so an unsettled sale never decrements.
    """
    _require_open(sale)
    if product is None:
        raise ValueError("add_product_item needs a product")
    if product.salon_id != sale.salon_id:
        raise ValueError("product does not belong to the sale's salon")
    return SaleItem.objects.create(
        sale=sale,
        kind=SaleItem.Kind.PRODUCT,
        product=product,
        description=product.name,
        quantity=_quantity(quantity),
        unit_price=_money(
            product.price if unit_price is None else unit_price, "unit_price"
        ),
    )


def add_series_item(sale, unit_price, description="", quantity=1):
    """Append a series/package line to an open ``sale`` and return it.

    A series item links neither a service nor a product (both stay
    null): ``description`` and ``unit_price`` are the snapshot, taken
    at add time like every other line. It moves no stock — only
    product lines do, at :func:`complete_sale` time.
    """
    _require_open(sale)
    return SaleItem.objects.create(
        sale=sale,
        kind=SaleItem.Kind.SERIES,
        description=description or "",
        quantity=_quantity(quantity),
        unit_price=_money(unit_price, "unit_price"),
    )


def complete_sale(sale, provider, method=None):
    """Settle an open ``sale`` via ``provider``; return its receipt.

    Records the completed ``Payment``, marks the sale ``COMPLETED``,
    appends one SALE ``StockMovement`` per product line, and builds
    the receipt (``checkout.receipts.build_receipt``). On a failed
    charge, records a ``FAILED`` payment, leaves the sale open with
    stock and receipts untouched, and raises ``ValueError``.
    """
    _require_open(sale)
    if provider is None:
        raise ValueError("complete_sale needs a payment provider")
    if not list(sale.items.all()):
        raise ValueError("cannot complete an empty sale")
    total = sale.total
    if total <= 0:
        raise ValueError("cannot complete a sale with a non-positive total")
    if method is None:
        method = getattr(provider, "name", "")
    if method not in dict(Payment.Method.choices):
        raise ValueError("complete_sale needs a core tender method")
    result = provider.charge(total, reference=f"sale-{sale.pk}")
    if not result.success:
        Payment.objects.create(
            sale=sale,
            method=method,
            amount=total,
            status=Payment.Status.FAILED,
            provider_reference=result.reference or "",
        )
        raise ValueError(result.message or "payment failed")
    with transaction.atomic():
        Payment.objects.create(
            sale=sale,
            method=method,
            amount=total,
            status=result.status,
            provider_reference=result.reference or "",
        )
        sale.status = Sale.Status.COMPLETED
        sale.completed_at = timezone.now()
        sale.save(update_fields=["status", "completed_at"])
        for item in sale.items.filter(kind=SaleItem.Kind.PRODUCT, product__isnull=False):
            StockMovement.objects.create(
                product=item.product,
                kind=StockMovement.Kind.SALE,
                quantity_delta=-item.quantity,
                note=f"Sale #{sale.pk}",
            )
        return build_receipt(sale)
