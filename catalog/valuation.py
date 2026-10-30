"""Stock valuation service for the catalog.

Backend only — no views, templates, or UI.

Valuation basis — stated honestly: ``Product`` carries exactly one
money field, ``price``, which is the product's selling (retail)
price. There is no cost / wholesale price field on the model (and
this service adds none), so the value computed here is **retail
value** — what the on-hand stock would sell for at current prices —
not cost value, and it must not be reported as cost, margin, or
profit.

Stock is derived, never stored: each product's on-hand quantity is
the sum of its ``StockMovement`` deltas — the movement log is the
one source of truth, so a product with no movements has 0 on hand.
The report is a single annotated query (one ``SUM`` per product),
not a per-product ``current_stock`` loop.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum, Value
from django.db.models.functions import Coalesce

from catalog.models import Product

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class ValuationRow:
    """One product's valuation.

    ``on_hand`` is the movement-derived stock at report time,
    ``unit_price`` is copied from ``Product.price`` (the retail /
    selling price — see the module docstring), and ``retail_value``
    is ``on_hand * unit_price``. ``sku`` / ``barcode`` are copied
    from the product so a row is a self-contained record.
    """

    product: Product
    sku: str
    barcode: str
    on_hand: int
    unit_price: Decimal
    retail_value: Decimal

    @property
    def current_stock(self):
        """Alias for ``on_hand``."""
        return self.on_hand

    @property
    def price(self):
        """Alias for ``unit_price``."""
        return self.unit_price

    @property
    def value(self):
        """Alias for ``retail_value``."""
        return self.retail_value

    @property
    def line_value(self):
        """Alias for ``retail_value``."""
        return self.retail_value


@dataclass(frozen=True)
class StockValuation:
    """Salon-wide valuation: per-product rows plus totals.

    ``total_retail_value`` is the sum of every row's
    ``retail_value`` and ``total_on_hand`` the sum of every row's
    ``on_hand``. Iterating / taking ``len()`` delegates to ``rows``.
    """

    salon_id: int
    rows: tuple
    total_on_hand: int
    total_retail_value: Decimal

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    @property
    def total_value(self):
        """Alias for ``total_retail_value``."""
        return self.total_retail_value

    @property
    def total_units(self):
        """Alias for ``total_on_hand``."""
        return self.total_on_hand


def stock_valuation(salon):
    """Return the stock valuation for ``salon``.

    Considers only ``salon``'s **active** products (``active=False``
    products are excluded entirely, however many movements they
    have). Every active product appears as a row — including
    products with no movements (0 on hand, ``ZERO`` retail value)
    and products whose derived on-hand is negative (their retail
    value is negative too: the ledger is reported as it stands,
    never clamped).

    Returns a :class:`StockValuation` whose rows are ordered by
    ``retail_value`` descending, then product name and id so ties
    are deterministic, and whose totals are the sums over the rows.
    """
    products = (
        Product.objects.filter(salon=salon, active=True)
        .annotate(
            _on_hand=Coalesce(Sum("stock_movements__quantity_delta"), Value(0))
        )
        .order_by("name", "id")
    )
    rows = []
    total_on_hand = 0
    total_retail_value = ZERO
    for product in products:
        on_hand = product._on_hand
        retail_value = (product.price * on_hand).quantize(ZERO)
        rows.append(
            ValuationRow(
                product=product,
                sku=product.sku,
                barcode=product.barcode,
                on_hand=on_hand,
                unit_price=product.price,
                retail_value=retail_value,
            )
        )
        total_on_hand += on_hand
        total_retail_value += retail_value
    rows.sort(key=lambda r: (-r.retail_value, r.product.name, r.product.pk))
    return StockValuation(
        salon_id=getattr(salon, "pk", salon),
        rows=tuple(rows),
        total_on_hand=total_on_hand,
        total_retail_value=total_retail_value.quantize(ZERO),
    )


#: Short alias, mirroring ``low_stock.low_stock`` naming convenience.
valuation = stock_valuation
