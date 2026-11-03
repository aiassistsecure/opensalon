"""Per-product margin report for the catalog.

Backend only — no views, templates, or UI. Read-only: every figure
is derived at call time; nothing is created, edited, or deleted.

Units and retail revenue are reused verbatim from
:func:`catalog.product_sales.product_sales` — this module never
re-implements the sales aggregation, so margin can never disagree
with the sales report about what was sold or taken (completed
product sale lines only, snapshot revenue; see that module).

CAVEAT — read before quoting any margin figure: ``SaleItem`` has
no cost snapshot, so margin uses the product's CURRENT
``cost_price`` (``catalog.models.Product.cost_price``). ``cost``
is ``cost_price * units_sold`` at report time, ``margin`` is
``retail_revenue - cost``, and ``margin_percent`` is
``margin / retail_revenue * 100``. If a product's cost has changed
since a sale was taken, that sale's margin here is restated at
today's cost — this is a current-cost margin, not the margin that
was actually earned on the day.

``cost_price`` is nullable: a product with no cost recorded has
unknown cost, never zero cost. Its ``unit_cost``, ``cost``,
``margin``, and ``margin_percent`` are all ``None`` — an unknown
margin is reported as unknown, not fabricated as a 100% margin.

``margin_percent`` is a ``Decimal`` percentage (x100) to two
places, or the ``None`` sentinel when ``retail_revenue`` is zero
(no revenue means no meaningful percentage — mirroring the
``None``-on-zero-denominator convention of sibling reports).
Money is ``Decimal`` throughout, never float.

Rows cover every product of the salon (the sales report's rows:
active or not, sold or not) in the sales report's order:
``retail_revenue`` descending, ``units_sold`` descending, then
product name and id.

Optional window: ``product_margin`` accepts the same optional
``start`` / ``end`` (aliases ``start_date`` / ``end_date``) as
:func:`catalog.product_sales.product_sales` and passes them to
that service verbatim, so windowed units/revenue — and therefore
``cost`` (= current ``cost_price`` x windowed units), ``margin``,
and ``margin_percent`` — follow the window exactly as the sales
report defines it. Rows and the report carry the normalised
``start_date`` / ``end_date``. No window is the historic
all-time report, unchanged.
"""
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from catalog.product_sales import product_sales

ZERO = Decimal("0.00")
_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class ProductMarginRow:
    """One product's margin (module docstring defines each field).

    ``unit_cost`` is the product's current ``cost_price``;
    ``cost`` / ``margin`` / ``margin_percent`` are ``None`` when
    the product has no cost recorded, and ``margin_percent`` is
    also ``None`` when revenue is zero. ``sku`` / ``barcode`` are
    copied from the product so a row is a self-contained record.
    """

    product: object
    sku: str
    barcode: str
    units_sold: int
    retail_revenue: Decimal
    unit_cost: Decimal | None
    cost: Decimal | None
    margin: Decimal | None
    margin_percent: Decimal | None
    start_date: date = None
    end_date: date = None


@dataclass(frozen=True)
class ProductMarginReport:
    """Salon-wide product margin: per-product rows plus totals.

    ``total_cost`` / ``total_margin`` sum only the rows that carry
    them (products with a recorded cost); products without a cost
    contribute to the units / revenue totals but not to the cost
    or margin totals. Iterating / ``len()`` delegate to ``rows``.
    """

    salon_id: int
    rows: tuple
    total_units_sold: int
    total_retail_revenue: Decimal
    total_cost: Decimal
    total_margin: Decimal
    start_date: date = None
    end_date: date = None
    sales_scope: str = "all_time"

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)


def product_margin(salon, start=None, end=None, *, start_date=None, end_date=None):
    """Return the per-product margin report for ``salon``.

    See the module docstring for the full contract — above all the
    current-cost caveat: ``SaleItem`` has no cost snapshot, so
    cost is the product's current ``cost_price`` times the units
    the sales report attributes to it. The optional window is
    passed to the sales report verbatim.
    """
    sales = product_sales(salon, start=start, end=end,
                          start_date=start_date, end_date=end_date)
    rows = []
    total_cost = ZERO
    total_margin = ZERO
    for sold in sales.rows:
        revenue = sold.retail_revenue
        unit_cost = sold.product.cost_price
        if unit_cost is None:
            cost = margin = margin_percent = None
        else:
            cost = (unit_cost * sold.units_sold).quantize(ZERO)
            margin = (revenue - cost).quantize(ZERO)
            if revenue == 0:
                margin_percent = None
            else:
                margin_percent = (margin * 100 / revenue).quantize(
                    _CENTS, rounding=ROUND_HALF_UP
                )
            total_cost += cost
            total_margin += margin
        rows.append(
            ProductMarginRow(
                product=sold.product,
                sku=sold.sku,
                barcode=sold.barcode,
                units_sold=sold.units_sold,
                retail_revenue=revenue,
                unit_cost=unit_cost,
                cost=cost,
                margin=margin,
                margin_percent=margin_percent,
                start_date=sales.start_date,
                end_date=sales.end_date,
            )
        )
    return ProductMarginReport(
        salon_id=sales.salon_id,
        rows=tuple(rows),
        total_units_sold=sales.total_units_sold,
        total_retail_revenue=sales.total_retail_revenue,
        total_cost=total_cost.quantize(ZERO),
        total_margin=total_margin.quantize(ZERO),
        start_date=sales.start_date,
        end_date=sales.end_date,
        sales_scope=sales.sales_scope,
    )


#: Aliases, mirroring the naming convenience in sibling services.
margin_by_product = product_margin
get_product_margin = product_margin
