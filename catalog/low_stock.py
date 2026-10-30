"""Low-stock report service for the catalog.

Backend only — no views, templates, or UI.

``Product`` has no reorder-threshold field (and this service adds
none), so the threshold is a caller-supplied argument to
:func:`low_stock`, defaulting to :data:`DEFAULT_LOW_STOCK_THRESHOLD`.
A salon that reorders at a different level passes its own value;
nothing about the threshold is stored.

Stock is derived, never stored: each product's on-hand quantity is
the sum of its ``StockMovement`` deltas — the movement log is the
one source of truth, so a product with no movements has 0 on hand.
The report is a single annotated query (one ``SUM`` per product),
not a per-product ``current_stock`` loop.
"""
from dataclasses import dataclass

from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from catalog.models import Product

#: Default reorder threshold: a product is low on stock when its
#: derived on-hand quantity is at or below this many units.
DEFAULT_LOW_STOCK_THRESHOLD = 5


@dataclass(frozen=True)
class LowStockRow:
    """One low-stock product.

    ``on_hand`` is the movement-derived stock at report time and
    ``threshold`` is the threshold the product qualified under.
    ``sku`` / ``barcode`` are copied from the product so a row is a
    self-contained record for reordering or scanning.
    """

    product: Product
    sku: str
    barcode: str
    on_hand: int
    threshold: int

    @property
    def current_stock(self):
        """Alias for ``on_hand``."""
        return self.on_hand

    @property
    def reorder_threshold(self):
        """Alias for ``threshold``."""
        return self.threshold


def _clean_threshold(threshold):
    if threshold is None:
        return DEFAULT_LOW_STOCK_THRESHOLD
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
        raise ValueError("threshold must be a non-negative integer or None")
    return threshold


def low_stock(salon, threshold=None):
    """Return low-stock rows for ``salon``, lowest on hand first.

    A product qualifies when its movement-derived on-hand quantity
    is at or below ``threshold`` (default
    :data:`DEFAULT_LOW_STOCK_THRESHOLD`; see the module docstring
    for why the threshold is an argument, not a model field).
    Products with no movements count as 0 on hand and therefore
    qualify under any non-negative threshold.

    Returns a list of :class:`LowStockRow` ordered by ``on_hand``
    ascending, then product name and id so ties are deterministic.
    Only ``salon``'s products are considered.
    """
    threshold = _clean_threshold(threshold)
    products = (
        Product.objects.filter(salon=salon)
        .annotate(
            _on_hand=Coalesce(Sum("stock_movements__quantity_delta"), Value(0))
        )
        .filter(_on_hand__lte=threshold)
        .order_by("_on_hand", "name", "id")
    )
    return [
        LowStockRow(
            product=product,
            sku=product.sku,
            barcode=product.barcode,
            on_hand=product._on_hand,
            threshold=threshold,
        )
        for product in products
    ]
