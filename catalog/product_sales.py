"""Per-product sales and stock-turns report for the catalog.

Backend only — no views, templates, or UI. Read-only: every figure
is derived at call time from the rows that are the one source of
truth for their fact; nothing is created, edited, or deleted.

Sales source — completed checkout lines only: units and revenue
come from ``checkout`` ``SaleItem`` rows whose sale is
``COMPLETED``, whose line ``kind`` is ``PRODUCT``, and whose
product is linked and in this salon. Open/voided sales, service
and series lines, and unlinked product lines never count. Revenue
is snapshot money actually taken — ``quantity * unit_price``
summed over the lines — so later price changes never rewrite past
revenue. Money is ``Decimal`` throughout, never float.

Stock turns: stock is derived, never stored (the ``StockMovement``
ledger is the source of truth, as in :mod:`catalog.valuation`).
``current_stock`` is the derived level after the last movement
(0 with no movements). ``average_stock`` is the mean of the
derived levels *after each movement*, in ledger order
(``created_at``, then id) — the average stock the product
actually sat at; 0 with no movements. ``stock_turns`` is
``units_sold / average_stock``, safe on zero stock: an average
stock of 0 reports turns of ``Decimal("0.0000")``, never a
division error. Negative derived levels are reported as they
stand, never clamped.

Rows cover every product of the salon — active or not, since a
retired product's sales history must not vanish — ordered by
``retail_revenue`` descending, then ``units_sold`` descending,
then product name and id.

Optional window (``start`` / ``end``, aliases ``start_date`` /
``end_date``): each bound may be a ``date``, ``datetime``, or ISO
date string, is inclusive, and covers whole local days in the
salon's timezone. When a window is given, ``units_sold`` and
``retail_revenue`` count only sales whose effective date — the
sale's ``completed_at`` when set, otherwise its ``created_at``
(the codebase-wide convention) — falls in the window. Either
bound may be given alone. A reversed window raises ``ValueError``.

STOCK SCOPE — never silently mixed: ``current_stock``,
``average_stock``, and ``stock_turns`` are ALWAYS derived
all-time, window or not. ``stock_turns`` is all-time units sold
over all-time average stock, so a windowed row's turns do NOT
use its windowed units. Rows and the report document this
explicitly: ``stock_scope == "all_time"`` always, while
``sales_scope`` is ``"windowed"`` when a window is given and
``"all_time"`` otherwise, and ``start_date`` / ``end_date``
carry the normalised window (``None`` when unbounded). With no
window the report is exactly the historic all-time report.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import ExpressionWrapper, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from catalog.models import Product, StockMovement
from checkout.models import Sale, SaleItem

ZERO = Decimal("0.00")
_TURNS_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class ProductSalesRow:
    """One product's sales and stock turns (module docstring
    defines each field). ``sku`` / ``barcode`` are copied from
    the product so a row is a self-contained record."""

    product: Product
    sku: str
    barcode: str
    units_sold: int
    retail_revenue: Decimal
    current_stock: int
    average_stock: Decimal
    stock_turns: Decimal
    # Scope documentation, never silently mixed: the sales figures
    # above follow ``sales_scope`` / the window bounds; the stock
    # figures above are always all-time (``stock_scope``).
    start_date: date = None
    end_date: date = None
    sales_scope: str = "all_time"
    stock_scope: str = "all_time"


@dataclass(frozen=True)
class ProductSalesReport:
    """Salon-wide product sales: per-product rows plus totals
    (the sums over every row). Iterating / ``len()`` delegate
    to ``rows``."""

    salon_id: int
    rows: tuple
    total_units_sold: int
    total_retail_revenue: Decimal
    start_date: date = None
    end_date: date = None
    sales_scope: str = "all_time"
    stock_scope: str = "all_time"

    @property
    def window_start(self):
        return self.start_date

    @property
    def window_end(self):
        return self.end_date

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)


def _average_stock(product):
    """Mean derived stock level after each of ``product``'s movements.

    Returns ``Decimal("0")`` when the product has no movements.
    Levels are taken in ledger order and reported as they stand,
    including negative levels from an oversold ledger.
    """
    deltas = list(
        StockMovement.objects.filter(product=product)
        .order_by("created_at", "id")
        .values_list("quantity_delta", flat=True)
    )
    if not deltas:
        return Decimal("0")
    level = 0
    total = 0
    for delta in deltas:
        level += delta
        total += level
    return (Decimal(total) / Decimal(len(deltas))).quantize(_TURNS_PLACES)


def _salon_tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_local_date(value, tz):
    if value is None:
        return None
    if isinstance(value, str):
        value = date.fromisoformat(value)
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return value.astimezone(tz).date()
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError("window bounds must be a date, datetime, or ISO date string")


def _resolve_window(salon, start, end, start_date, end_date):
    tz = _salon_tz(salon)
    first = _as_local_date(start if start is not None else start_date, tz)
    last = _as_local_date(end if end is not None else end_date, tz)
    if first is not None and last is not None and last < first:
        raise ValueError("window end must not be before window start")
    return first, last, tz


def _window_q(first, last, tz):
    """Q matching lines whose sale's effective date is in-window."""
    if first is None and last is None:
        return None
    start_dt = (datetime.combine(first, time.min, tzinfo=tz)
                if first is not None else None)
    end_dt = (datetime.combine(last + timedelta(days=1), time.min, tzinfo=tz)
              if last is not None else None)
    completed = Q()
    created = Q(sale__completed_at__isnull=True)
    if start_dt is not None:
        completed &= Q(sale__completed_at__gte=start_dt)
        created &= Q(sale__created_at__gte=start_dt)
    if end_dt is not None:
        completed &= Q(sale__completed_at__lt=end_dt)
        created &= Q(sale__created_at__lt=end_dt)
    return completed | created


def _sales_agg(salon, window_q):
    qs = SaleItem.objects.filter(
        sale__salon=salon, sale__status=Sale.Status.COMPLETED,
        kind=SaleItem.Kind.PRODUCT, product__isnull=False)
    if window_q is not None:
        qs = qs.filter(window_q)
    return {
        row["product_id"]: row
        for row in qs.values("product_id").annotate(
            units=Coalesce(Sum("quantity"), Value(0)),
            revenue=Coalesce(
                Sum(ExpressionWrapper(
                    F("quantity") * F("unit_price"),
                    output_field=SaleItem._meta.get_field("unit_price"))),
                Value(ZERO)))
    }


def product_sales(salon, start=None, end=None, *, start_date=None, end_date=None):
    """Return the per-product sales + stock turns report for ``salon``.

    See the module docstring for the full contract: completed
    product sale lines only, snapshot revenue, movement-derived
    current and average stock, turns safe on zero average stock,
    every product of the salon as a row (sold or not, active or
    not), ordered by revenue descending, units descending, then
    product name and id. The optional window (``start`` / ``end``,
    aliases ``start_date`` / ``end_date``) windows units/revenue
    only; stock figures stay all-time, documented on the rows.
    """
    first, last, tz = _resolve_window(salon, start, end, start_date, end_date)
    windowed = first is not None or last is not None
    products = Product.objects.filter(salon=salon).order_by("name", "id")
    sales = _sales_agg(salon, _window_q(first, last, tz))
    all_time = sales if not windowed else _sales_agg(salon, None)
    on_hand = {
        row["product_id"]: row["total"]
        for row in StockMovement.objects.filter(product__salon=salon)
        .values("product_id")
        .annotate(total=Coalesce(Sum("quantity_delta"), Value(0)))
    }
    rows = []
    total_units_sold = 0
    total_retail_revenue = ZERO
    for product in products:
        sold = sales.get(product.pk, {})
        units_sold = sold.get("units", 0) or 0
        retail_revenue = (sold.get("revenue", ZERO) or ZERO).quantize(ZERO)
        all_units = all_time.get(product.pk, {}).get("units", 0) or 0
        average_stock = _average_stock(product)
        if average_stock == 0:
            stock_turns = Decimal("0.0000")
        else:
            # All-time turns: all-time units over all-time average
            # stock, even on a windowed report (module docstring).
            stock_turns = (Decimal(all_units) / average_stock).quantize(
                _TURNS_PLACES
            )
        rows.append(
            ProductSalesRow(
                product=product,
                sku=product.sku,
                barcode=product.barcode,
                units_sold=units_sold,
                retail_revenue=retail_revenue,
                current_stock=on_hand.get(product.pk, 0) or 0,
                average_stock=average_stock,
                stock_turns=stock_turns,
                start_date=first,
                end_date=last,
                sales_scope="windowed" if windowed else "all_time",
                stock_scope="all_time",
            )
        )
        total_units_sold += units_sold
        total_retail_revenue += retail_revenue
    rows.sort(
        key=lambda r: (
            -r.retail_revenue,
            -r.units_sold,
            r.product.name,
            r.product.pk,
        )
    )
    return ProductSalesReport(
        salon_id=getattr(salon, "pk", salon),
        rows=tuple(rows),
        total_units_sold=total_units_sold,
        total_retail_revenue=total_retail_revenue.quantize(ZERO),
        start_date=first,
        end_date=last,
        sales_scope="windowed" if windowed else "all_time",
        stock_scope="all_time",
    )


#: Aliases, mirroring the naming convenience in sibling services.
sales_by_product = product_sales
get_product_sales = product_sales
