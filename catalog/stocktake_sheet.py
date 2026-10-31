"""Stocktake sheet service for the catalog.

Backend only — no views, templates, or UI.

A stocktake sheet is the expected-stock side of a physical count:
one row per active product at the salon, giving the counter the
product's name, its barcode/SKU (for scanner or shelf-label checks),
and the on-hand quantity the count will be checked against. The
count itself, and the reconciling movements it produces, live in
:mod:`catalog.stocktake`; this service only reads.

Stock is derived, never stored: each product's on-hand quantity is
the sum of its ``StockMovement`` deltas — the movement log is the
one source of truth, so a product with no movements has 0 on hand.
The sheet is a single annotated query (one ``SUM`` per product),
not a per-product ``current_stock`` loop.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from catalog.models import Product


@dataclass(frozen=True)
class StocktakeSheetRow:
    """One product's expected-stock line on a stocktake sheet.

    ``on_hand`` is the movement-derived stock at sheet time and
    ``retail_price`` is copied from ``Product.price`` (the selling
    price). ``name`` / ``sku`` / ``barcode`` are copied from the
    product so a row is a self-contained record.
    """

    product: Product
    name: str
    sku: str
    barcode: str
    on_hand: int
    retail_price: Decimal

    @property
    def current_stock(self):
        """Alias for ``on_hand``."""
        return self.on_hand

    @property
    def price(self):
        """Alias for ``retail_price``."""
        return self.retail_price


def stocktake_sheet(salon):
    """Return the stocktake sheet for ``salon``.

    Considers only ``salon``'s **active** products (``active=False``
    products are excluded entirely, however many movements they
    have). Every active product appears as a row — including
    products with no movements (0 on hand) — so a counter can check
    the full shelf against the sheet.

    Returns a list of :class:`StocktakeSheetRow` ordered by product
    name, then id so same-named products are deterministic.
    """
    products = (
        Product.objects.filter(salon=salon, active=True)
        .annotate(
            _on_hand=Coalesce(Sum("stock_movements__quantity_delta"), Value(0))
        )
        .order_by("name", "id")
    )
    return [
        StocktakeSheetRow(
            product=product,
            name=product.name,
            sku=product.sku,
            barcode=product.barcode,
            on_hand=product._on_hand,
            retail_price=product.price,
        )
        for product in products
    ]


#: Short alias, mirroring ``low_stock.low_stock`` naming convenience.
sheet = stocktake_sheet
