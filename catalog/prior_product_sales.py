"""Prior-period comparisons for product sales and product margin.

Backend only — no views, templates, or UI. Read-only. Built ON
TOP of :func:`catalog.product_sales.product_sales` and
:func:`catalog.margin.product_margin` — figures for both windows
are those services' verbatim; never recomputed. ``product_margin``
reuses ``product_sales`` verbatim as it does today, so margin can
never disagree with sales, and the current-cost caveat of
:mod:`catalog.margin` applies unchanged (cost is the product's
CURRENT ``cost_price``; no cost recorded means ``None``, never a
fabricated zero). For an inclusive current window ``[start, end]``
of ``length`` days, the prior period is ``[start - length,
start - 1]`` — the period arithmetic of
:mod:`catalog.prior_movement_summary`. Both bounds are required:
a missing bound raises ``ValueError``; a reversed window raises
the underlying service's ``ValueError``. Each metric carries
``current``, ``prior``, ``delta`` and ``percent_change``
(Decimal, two places, ROUND_HALF_UP), ``None`` when prior is
zero — or, for nullable margin figures, when either side is
``None``. ``by_product`` is the union of both windows' rows in
current-report order (prior-only products appended in prior
order). Stock figures are all-time in both windows by the sales
service's scope rule, so they carry no delta; the verbatim rows
sit on each row's ``current`` / ``prior``.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from catalog.margin import product_margin
from catalog.product_sales import product_sales

__all__ = ["MetricDelta", "ProductSalesDelta", "ProductMarginDelta",
           "PriorProductSales", "PriorProductSalesReport",
           "PriorProductMargin", "PriorProductMarginReport",
           "prior_product_sales", "prior_period_product_sales",
           "compare_product_sales", "get_prior_product_sales",
           "prior_product_margin", "prior_period_product_margin",
           "compare_product_margin", "get_prior_product_margin"]
_CENT = Decimal("0.01")
ZERO = Decimal("0.00")


@dataclass(frozen=True)
class MetricDelta:
    """One metric in both periods, with its change."""

    component: str
    current: object = None
    prior: object = None
    delta: object = None
    percent_change: Decimal | None = None

    @property
    def name(self): return self.component
    @property
    def previous(self): return self.prior
    @property
    def change(self): return self.delta
    @property
    def pct_change(self): return self.percent_change

    def as_dict(self):
        return {"component": self.component, "current": self.current,
                "prior": self.prior, "delta": self.delta,
                "percent_change": self.percent_change}


def _pct_change(current, prior):
    if current is None or not prior:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior) * 100
            ).quantize(_CENT, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    current, prior = int(current), int(prior)
    return MetricDelta(name, current, prior, current - prior,
                       _pct_change(current, prior))


def _money_delta(name, current, prior):
    if current is None or prior is None:
        return MetricDelta(name, current, prior, None, None)
    current, prior = Decimal(current), Decimal(prior)
    return MetricDelta(name, current, prior,
                       (current - prior).quantize(_CENT),
                       _pct_change(current, prior))


def _windows(salon, service, start, end, start_date, end_date, label):
    """Call ``service`` verbatim for the current and prior windows."""
    current = service(salon, start=start, end=end,
                      start_date=start_date, end_date=end_date)
    first, last = current.start_date, current.end_date
    if first is None or last is None:
        raise ValueError(f"{label} needs both a start and an end date")
    length = (last - first).days + 1
    prior_end = first - timedelta(days=1)
    prior_start = first - timedelta(days=length)
    return (current, service(salon, start=prior_start, end=prior_end),
            first, last, prior_start, prior_end)


def _union_rows(current_rows, prior_rows):
    """(current, prior) row pairs, union by product, current order."""
    prior_by_pk = {r.product.pk: r for r in prior_rows}
    seen, pairs = set(), []
    for row in current_rows:
        seen.add(row.product.pk)
        pairs.append((row, prior_by_pk.get(row.product.pk)))
    pairs += [(None, r) for r in prior_rows if r.product.pk not in seen]
    return pairs


class _Comparison:
    """Shared comparison-report behaviour (dates, lookup, dict)."""

    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    length = days
    rows = property(lambda self: self.by_product)  # noqa: E731
    per_product = rows

    def for_product(self, product):
        key = getattr(product, "pk", product)
        return next((r for r in self.by_product if r.product_id == key), None)

    def _totals_dict(self):
        return {}

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"salon_id": self.salon_id, "start_date": iso(self.start_date),
                "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                **{k: v.as_dict() for k, v in self._totals_dict().items()},
                "by_product": [r.as_dict() for r in self.by_product]}

    __iter__ = lambda self: iter(self.by_product)  # noqa: E731
    __len__ = lambda self: len(self.by_product)  # noqa: E731


@dataclass(frozen=True)
class ProductSalesDelta:
    """One product's sales totals in both periods."""

    product: object = None
    product_id: int = None
    product_name: str = ""
    sku: str = ""
    barcode: str = ""
    current: object = None
    prior: object = None
    units_sold: MetricDelta = None
    retail_revenue: MetricDelta = None

    @property
    def name(self): return self.product_name

    def as_dict(self):
        return {"product_id": self.product_id,
                "product_name": self.product_name, "sku": self.sku,
                "barcode": self.barcode,
                "units_sold": self.units_sold.as_dict(),
                "retail_revenue": self.retail_revenue.as_dict()}


@dataclass(frozen=True)
class PriorProductSales(_Comparison):
    """Product sales comparison: current window vs prior."""

    salon_id: int = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    total_units_sold: MetricDelta = None
    total_retail_revenue: MetricDelta = None
    by_product: list = field(default_factory=list)

    def _totals_dict(self):
        return {"total_units_sold": self.total_units_sold,
                "total_retail_revenue": self.total_retail_revenue}

PriorProductSalesReport = PriorProductSales


def prior_product_sales(salon, start=None, end=None, *,
                        start_date=None, end_date=None):
    """Return the prior-period product sales comparison for ``salon``.

    ``start`` / ``end`` (aliases ``start_date`` / ``end_date``)
    are the current window's inclusive bounds, exactly as in
    :func:`catalog.product_sales.product_sales`, called verbatim
    for both windows. Both bounds are required. Records nothing.
    """
    current, prior, first, last, p_first, p_last = _windows(
        salon, product_sales, start, end, start_date, end_date,
        "prior_product_sales")
    by_product = []
    for cur, pri in _union_rows(current.rows, prior.rows):
        ref = cur or pri
        by_product.append(ProductSalesDelta(
            product=ref.product, product_id=ref.product.pk,
            product_name=ref.product.name, sku=ref.sku,
            barcode=ref.barcode, current=cur, prior=pri,
            units_sold=_count_delta("units_sold",
                                    cur.units_sold if cur else 0,
                                    pri.units_sold if pri else 0),
            retail_revenue=_money_delta(
                "retail_revenue", cur.retail_revenue if cur else ZERO,
                pri.retail_revenue if pri else ZERO)))
    return PriorProductSales(
        salon_id=current.salon_id, start_date=first, end_date=last,
        prior_start_date=p_first, prior_end_date=p_last,
        current=current, prior=prior,
        total_units_sold=_count_delta("total_units_sold",
                                      current.total_units_sold,
                                      prior.total_units_sold),
        total_retail_revenue=_money_delta(
            "total_retail_revenue", current.total_retail_revenue,
            prior.total_retail_revenue),
        by_product=by_product)


@dataclass(frozen=True)
class ProductMarginDelta:
    """One product's margin figures in both periods."""

    product: object = None
    product_id: int = None
    product_name: str = ""
    sku: str = ""
    barcode: str = ""
    unit_cost: Decimal | None = None
    current: object = None
    prior: object = None
    units_sold: MetricDelta = None
    retail_revenue: MetricDelta = None
    cost: MetricDelta = None
    margin: MetricDelta = None
    margin_percent: MetricDelta = None

    @property
    def name(self): return self.product_name

    def as_dict(self):
        return {"product_id": self.product_id,
                "product_name": self.product_name, "sku": self.sku,
                "barcode": self.barcode, "unit_cost": self.unit_cost,
                "units_sold": self.units_sold.as_dict(),
                "retail_revenue": self.retail_revenue.as_dict(),
                "cost": self.cost.as_dict(),
                "margin": self.margin.as_dict(),
                "margin_percent": self.margin_percent.as_dict()}


@dataclass(frozen=True)
class PriorProductMargin(_Comparison):
    """Product margin comparison: current window vs prior."""

    salon_id: int = None
    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    current: object = None
    prior: object = None
    total_units_sold: MetricDelta = None
    total_retail_revenue: MetricDelta = None
    total_cost: MetricDelta = None
    total_margin: MetricDelta = None
    by_product: list = field(default_factory=list)

    def _totals_dict(self):
        return {"total_units_sold": self.total_units_sold,
                "total_retail_revenue": self.total_retail_revenue,
                "total_cost": self.total_cost,
                "total_margin": self.total_margin}

PriorProductMarginReport = PriorProductMargin


def prior_product_margin(salon, start=None, end=None, *,
                         start_date=None, end_date=None):
    """Return the prior-period product margin comparison for ``salon``.

    Same window contract as :func:`prior_product_sales`, built on
    :func:`catalog.margin.product_margin` verbatim for both
    windows — current-cost caveat and ``None``-on-unknown-cost
    semantics included. Records nothing.
    """
    current, prior, first, last, p_first, p_last = _windows(
        salon, product_margin, start, end, start_date, end_date,
        "prior_product_margin")
    by_product = []
    for cur, pri in _union_rows(current.rows, prior.rows):
        ref = cur or pri
        by_product.append(ProductMarginDelta(
            product=ref.product, product_id=ref.product.pk,
            product_name=ref.product.name, sku=ref.sku,
            barcode=ref.barcode, unit_cost=ref.unit_cost,
            current=cur, prior=pri,
            units_sold=_count_delta("units_sold",
                                    cur.units_sold if cur else 0,
                                    pri.units_sold if pri else 0),
            retail_revenue=_money_delta(
                "retail_revenue", cur.retail_revenue if cur else ZERO,
                pri.retail_revenue if pri else ZERO),
            cost=_money_delta("cost", cur.cost if cur else None,
                              pri.cost if pri else None),
            margin=_money_delta("margin", cur.margin if cur else None,
                                pri.margin if pri else None),
            margin_percent=_money_delta(
                "margin_percent", cur.margin_percent if cur else None,
                pri.margin_percent if pri else None)))
    return PriorProductMargin(
        salon_id=current.salon_id, start_date=first, end_date=last,
        prior_start_date=p_first, prior_end_date=p_last,
        current=current, prior=prior,
        total_units_sold=_count_delta("total_units_sold",
                                      current.total_units_sold,
                                      prior.total_units_sold),
        total_retail_revenue=_money_delta(
            "total_retail_revenue", current.total_retail_revenue,
            prior.total_retail_revenue),
        total_cost=_money_delta("total_cost", current.total_cost,
                                prior.total_cost),
        total_margin=_money_delta("total_margin", current.total_margin,
                                  prior.total_margin),
        by_product=by_product)


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_product_sales = prior_product_sales
compare_product_sales = prior_product_sales
get_prior_product_sales = prior_product_sales
prior_period_product_margin = prior_product_margin
compare_product_margin = prior_product_margin
get_prior_product_margin = prior_product_margin
