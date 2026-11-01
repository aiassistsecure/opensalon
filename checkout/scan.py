"""Scan-to-add service for checkout.

Backend only — no views, templates, or UI. A standard
keyboard-wedge USB/Bluetooth scanner delivers one code string
(barcode or SKU) exactly as if typed; this module resolves that
code against the catalogue of the sale's own salon and appends
the product to the open sale via ``checkout.sales.add_product_item``,
so the line snapshots the product's current price and description
exactly like a manually added product line. No stock moves here:
the SALE movement is appended by ``complete_sale`` when the sale
actually settles, as for every other product line.

Fail-closed: an unknown or blank code, a code that belongs only
to another salon's product, and an inactive product all raise
``ValidationError`` and add nothing to the sale. Resolution is
salon-scoped from the start (never a global lookup), so a
cross-salon product can never leak onto a sale; when two salons
carry the same code, the sale's own salon wins. Within a salon,
barcode wins over SKU when a code somehow matches both, matching
``catalog.Product.lookup_by_scan``.
"""
from django.core.exceptions import ValidationError

from catalog.models import Product

from .models import Sale
from .sales import add_product_item


def _resolve_in_salon(salon_id, code):
    """Return the salon's product for ``code`` (barcode, then SKU)."""
    own = Product.objects.filter(salon_id=salon_id)
    return own.filter(barcode=code).first() or own.filter(sku=code).first()


def add_scanned_product(sale, code, quantity=1):
    """Add the product identified by scanned ``code`` to ``sale``.

    ``code`` is matched exactly (after stripping surrounding
    whitespace, as a scanner read may carry it) against the
    barcode, then the SKU, of products in the sale's salon only.
    Returns the created ``SaleItem`` at the product's current
    price. Raises ``ValidationError`` — adding nothing — when the
    sale is missing or not open, the code is blank or unknown in
    the sale's salon (including codes belonging only to another
    salon), or the resolved product is inactive.
    """
    if sale is None:
        raise ValidationError("add_scanned_product needs a sale")
    if sale.status != Sale.Status.OPEN:
        raise ValidationError("scan-to-add needs an open sale")
    code = (code or "").strip() if isinstance(code, str) else ""
    if not code:
        raise ValidationError("scanned code is blank")
    product = _resolve_in_salon(sale.salon_id, code)
    if product is None:
        raise ValidationError(f"no product in this salon matches code {code!r}")
    if not product.active:
        raise ValidationError(f"product {product.name!r} is inactive")
    return add_product_item(sale, product, quantity=quantity)
