"""Prior-period comparison for attach rate + service-category mix.

Backend only — no views, templates, or UI. Nothing is stored.
Extends :mod:`insights.prior_period` to :mod:`insights.attach_rate`
and :mod:`insights.category_mix`, mirroring
:mod:`insights.prior_staff_service`: equal-length prior window;
figures verbatim from those services, never re-derived;
``percent_change`` is a Decimal quantised to two places, ``None``
when prior is zero (``delta`` always present); reversed window
raises ``ValueError``. Category rows in only one period appear
with the missing side zero, keyed as the service groups them.
Rows order by current revenue descending, then name ascending.
CSV helpers follow :mod:`insights.prior_period_export` (Exit
Principle): money/percentages to two places, ``None`` as empty.

The attach comparison also carries ``daily``: a tuple of
offset-aligned per-day entries (day 1 vs day 1, day 2 vs day 2,
…, following :mod:`insights.prior_trend`'s per-day shape), taken
verbatim from :func:`insights.attach_rate.retail_attach_rate`'s
own ``RetailAttachRate.daily`` series for both windows — no new
counting path. Each entry carries its current and prior
:class:`~insights.attach_rate.AttachDay` plus count/money
deltas for ``service_sales``, ``attached_sales``,
``retail_revenue``, and ``service_revenue``; ``attach_rate`` is
a derived property of the source's ``AttachDay`` and follows
from the compared counts, so it carries no delta of its own.
The attach CSV gains one ``daily_<metric>`` row per entry and
metric, distinguished by appended ``offset`` / ``current_date``
/ ``prior_date`` columns (empty on the summary rows).
"""
import csv
import io
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .attach_rate import AttachDay, retail_attach_rate
from .category_mix import category_mix
from .prior_period import ComponentDelta, _as_window_date, _delta
from .services import ZERO

__all__ = [
    "AttachPriorComparison", "AttachDayDelta", "AttachPriorDayDelta",
    "PriorAttachDayDelta", "CategoryPriorDelta",
    "PriorCategoryMixComparison", "prior_period_attach_rate",
    "prior_period_category_mix", "compare_attach_rate",
    "compare_category_mix", "PRIOR_ATTACH_FIELDNAMES",
    "PRIOR_CATEGORY_FIELDNAMES", "export_prior_attach_csv",
    "export_prior_category_mix_csv",
]

_CENTS = Decimal("0.01")


def _count_delta(component, current, prior):
    return _delta(component, Decimal(current), Decimal(prior))


_DAILY_FIELDS = (
    "service_sales", "attached_sales", "retail_revenue",
    "service_revenue",
)


@dataclass(frozen=True)
class AttachDayDelta:
    """One offset-aligned per-day pair: current day vs prior day."""

    offset: int
    current: AttachDay
    prior: AttachDay
    service_sales: ComponentDelta
    attached_sales: ComponentDelta
    retail_revenue: ComponentDelta
    service_revenue: ComponentDelta

    @property
    def previous(self):
        return self.prior

    @property
    def date(self):
        return self.current.date

    @property
    def current_date(self):
        return self.current.date

    @property
    def prior_date(self):
        return self.prior.date

    @property
    def current_attach_rate(self):
        return self.current.attach_rate

    @property
    def prior_attach_rate(self):
        return self.prior.attach_rate

    @property
    def deltas(self):
        return {name: getattr(self, name) for name in _DAILY_FIELDS}


AttachPriorDayDelta = AttachDayDelta
PriorAttachDayDelta = AttachDayDelta


@dataclass(frozen=True)
class AttachPriorComparison:
    """Current vs prior :class:`RetailAttachRate`, with deltas."""

    current: object
    prior: object
    service_sales: ComponentDelta
    attached_sales: ComponentDelta
    attach_rate_percent: ComponentDelta
    service_revenue: ComponentDelta
    retail_revenue: ComponentDelta
    total_retail_revenue: ComponentDelta
    unattached_service_sales: ComponentDelta
    product_only_sales: ComponentDelta
    total_completed_sales: ComponentDelta
    retail_quantity: ComponentDelta
    daily: tuple = ()

    @property
    def previous(self):
        return self.prior

    @property
    def per_day(self):
        return self.daily

    @property
    def by_day(self):
        return self.daily

    @property
    def by_offset(self):
        return {r.offset: r for r in self.daily}

    @property
    def start_date(self):
        return self.current.start_date

    @property
    def end_date(self):
        return self.current.end_date

    @property
    def prior_start_date(self):
        return self.prior.start_date

    @property
    def prior_end_date(self):
        return self.prior.end_date

    @property
    def days(self):
        return self.current.days


@dataclass(frozen=True)
class CategoryPriorDelta:
    """One category row in both periods, with its change."""

    category: object | None
    category_name: str
    current: object | None
    prior: object | None
    revenue: ComponentDelta
    quantity: ComponentDelta
    current_sale_count: int
    prior_sale_count: int

    @property
    def name(self):
        return self.category_name

    @property
    def current_revenue_share_percent(self):
        return self.current.revenue_share_percent if self.current else None

    @property
    def prior_revenue_share_percent(self):
        return self.prior.revenue_share_percent if self.prior else None


class PriorCategoryMixComparison(list):
    """Current vs prior per-category delta rows, bounds attached."""

    def __init__(self, rows, *, start_date, end_date,
                 prior_start_date, prior_end_date):
        super().__init__(rows)
        self.start_date = start_date
        self.end_date = end_date
        self.prior_start_date = prior_start_date
        self.prior_end_date = prior_end_date
        self.days = (end_date - start_date).days + 1


def _window(salon, start_date, end_date, kwargs):
    if start_date is None:
        start_date = kwargs.pop("start", kwargs.pop("since", None))
    if end_date is None:
        end_date = kwargs.pop("end", kwargs.pop("until", None))
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    if start_date is None or end_date is None:
        raise ValueError("Both start_date and end_date are required.")
    start = _as_window_date(start_date, salon)
    end = _as_window_date(end_date, salon)
    if end < start:
        raise ValueError("end_date must be on or after start_date.")
    length = (end - start).days + 1
    return start, end, start - timedelta(days=length), \
        start - timedelta(days=1), length


def prior_period_attach_rate(salon, start_date=None, end_date=None,
                             **kwargs):
    """Return the attach rate for the current vs prior period."""
    start, end, p_start, p_end, length = _window(
        salon, start_date, end_date, kwargs)
    current = retail_attach_rate(salon, days=length, end_date=end)
    prior = retail_attach_rate(salon, days=length, end_date=p_end)
    daily = tuple(
        AttachDayDelta(
            offset=offset, current=cur, prior=pri,
            service_sales=_count_delta(
                "service_sales", cur.service_sales, pri.service_sales),
            attached_sales=_count_delta(
                "attached_sales", cur.attached_sales,
                pri.attached_sales),
            retail_revenue=_delta(
                "retail_revenue", cur.retail_revenue,
                pri.retail_revenue),
            service_revenue=_delta(
                "service_revenue", cur.service_revenue,
                pri.service_revenue),
        )
        for offset, (cur, pri) in enumerate(
            zip(current.daily, prior.daily)))
    return AttachPriorComparison(
        current=current, prior=prior,
        service_sales=_count_delta(
            "service_sales", current.service_sales, prior.service_sales),
        attached_sales=_count_delta(
            "attached_sales", current.attached_sales,
            prior.attached_sales),
        attach_rate_percent=_delta(
            "attach_rate_percent", current.attach_rate_percent,
            prior.attach_rate_percent),
        service_revenue=_delta(
            "service_revenue", current.service_revenue,
            prior.service_revenue),
        retail_revenue=_delta(
            "retail_revenue", current.retail_revenue,
            prior.retail_revenue),
        total_retail_revenue=_delta(
            "total_retail_revenue", current.total_retail_revenue,
            prior.total_retail_revenue),
        unattached_service_sales=_count_delta(
            "unattached_service_sales",
            current.unattached_service_sales,
            prior.unattached_service_sales),
        product_only_sales=_count_delta(
            "product_only_sales", current.product_only_sales,
            prior.product_only_sales),
        total_completed_sales=_count_delta(
            "total_completed_sales", current.total_completed_sales,
            prior.total_completed_sales),
        retail_quantity=_count_delta(
            "retail_quantity", current.retail_quantity,
            prior.retail_quantity),
        daily=daily,
    )


def prior_period_category_mix(salon, start_date=None, end_date=None,
                              **kwargs):
    """Return per-category mix for the current vs prior period."""
    start, end, p_start, p_end, _ = _window(
        salon, start_date, end_date, kwargs)
    current = category_mix(salon, start, end)
    prior = category_mix(salon, p_start, p_end)

    def key(row):
        return (("category", row.category_id)
                if row.category_id is not None else ("snapshot",))

    cur = {key(r): r for r in current}
    pri = {key(r): r for r in prior}
    rows = []
    for k in dict.fromkeys([*cur, *pri]):
        c, p = cur.get(k), pri.get(k)
        ref = c or p
        rows.append(CategoryPriorDelta(
            category=ref.category, category_name=ref.category_name,
            current=c, prior=p,
            revenue=_delta("revenue", c.revenue if c else ZERO,
                           p.revenue if p else ZERO),
            quantity=_count_delta(
                "quantity", c.quantity if c else 0,
                p.quantity if p else 0),
            current_sale_count=c.sale_count if c else 0,
            prior_sale_count=p.sale_count if p else 0,
        ))
    rows.sort(key=lambda r: (-r.revenue.current, r.category_name))
    return PriorCategoryMixComparison(
        rows, start_date=start, end_date=end,
        prior_start_date=p_start, prior_end_date=p_end)


compare_attach_rate = prior_period_attach_rate
compare_category_mix = prior_period_category_mix

PRIOR_ATTACH_FIELDNAMES = [
    "metric", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "current", "prior",
    "delta", "percent_change", "offset", "current_date",
    "prior_date",
]
PRIOR_CATEGORY_FIELDNAMES = [
    "category_name", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "current", "prior",
    "delta", "percent_change", "current_quantity", "prior_quantity",
    "current_sale_count", "prior_sale_count",
    "current_revenue_share_percent", "prior_revenue_share_percent",
]
_ATTACH_METRICS = (
    "service_sales", "attached_sales", "attach_rate_percent",
    "service_revenue", "retail_revenue", "total_retail_revenue",
    "unattached_service_sales", "product_only_sales",
    "total_completed_sales", "retail_quantity",
)
_COUNT_METRICS = (
    "service_sales", "attached_sales", "unattached_service_sales",
    "product_only_sales", "total_completed_sales", "retail_quantity",
)


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _fmt(metric, value):
    return str(int(Decimal(value))) if metric in _COUNT_METRICS \
        else _money(value)


def _write(rows, fieldnames):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames,
                            lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def _bounds(result):
    return {
        "current_start_date": result.start_date.isoformat(),
        "current_end_date": result.end_date.isoformat(),
        "prior_start_date": result.prior_start_date.isoformat(),
        "prior_end_date": result.prior_end_date.isoformat(),
    }


def export_prior_attach_csv(salon, start_date=None, end_date=None,
                            **kwargs):
    """Return the attach prior-period comparison as a CSV string.

    Summary metric rows first (``offset`` / ``current_date`` /
    ``prior_date`` empty), then one ``daily_<metric>`` row per
    offset-aligned per-day entry and daily metric, carrying that
    entry's offset and current/prior dates.
    """
    result = prior_period_attach_rate(salon, start_date, end_date,
                                      **kwargs)
    rows = [{
        "metric": name, **_bounds(result),
        "current": _fmt(name, getattr(result, name).current),
        "prior": _fmt(name, getattr(result, name).prior),
        "delta": _fmt(name, getattr(result, name).delta),
        "percent_change": _pct(getattr(result, name).percent_change),
        "offset": "", "current_date": "", "prior_date": "",
    } for name in _ATTACH_METRICS]
    for entry in result.daily:
        for name in _DAILY_FIELDS:
            comp = getattr(entry, name)
            rows.append({
                "metric": f"daily_{name}", **_bounds(result),
                "current": _fmt(name, comp.current),
                "prior": _fmt(name, comp.prior),
                "delta": _fmt(name, comp.delta),
                "percent_change": _pct(comp.percent_change),
                "offset": entry.offset,
                "current_date": entry.current_date.isoformat(),
                "prior_date": entry.prior_date.isoformat(),
            })
    return _write(rows, PRIOR_ATTACH_FIELDNAMES)


def export_prior_category_mix_csv(salon, start_date=None, end_date=None,
                                  **kwargs):
    """Return the category-mix prior-period comparison as CSV."""
    result = prior_period_category_mix(salon, start_date, end_date,
                                       **kwargs)
    return _write([{
        "category_name": r.category_name, **_bounds(result),
        "current": _money(r.revenue.current),
        "prior": _money(r.revenue.prior),
        "delta": _money(r.revenue.delta),
        "percent_change": _pct(r.revenue.percent_change),
        "current_quantity": int(r.quantity.current),
        "prior_quantity": int(r.quantity.prior),
        "current_sale_count": r.current_sale_count,
        "prior_sale_count": r.prior_sale_count,
        "current_revenue_share_percent": _pct(
            r.current_revenue_share_percent),
        "prior_revenue_share_percent": _pct(
            r.prior_revenue_share_percent),
    } for r in result], PRIOR_CATEGORY_FIELDNAMES)
