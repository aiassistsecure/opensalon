"""Service-category mix: revenue/count share by service category.

Backend only — no views, templates, or UI. Nothing is stored:
each figure is computed from the ``Sale`` / ``SaleItem`` rows
that own the fact, as in :mod:`insights.service_revenue`.

Definitions (the contract of this module)
-----------------------------------------
* Only ``SaleItem.Kind.SERVICE`` items on completed sales count
  (open/voided never count). A sale belongs to the day of its
  ``completed_at`` when set, otherwise its ``created_at``, judged
  in the salon's timezone; the range is inclusive at both ends.
* Rows group by the linked service's ``ServiceCategory`` (two
  distinct categories never merge, even with the same name).
  Items with no linked service group into one
  ``"Uncategorized"`` row with ``category=None``.
* ``revenue`` is the Decimal sum of line totals, never a float
  or ``None``. ``quantity`` sums quantities, ``line_count``
  counts items, ``sale_count`` counts distinct sales, and
  ``service_count`` counts distinct linked services.
* Shares are percentages (x100) of the window's service
  revenue / quantity, Decimals quantized to two places; a share
  is ``None`` when its window total is zero (no meaningful
  percentage), mirroring :mod:`insights.prior_period`.
* Rows rank by ``revenue`` descending, then name ascending.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q

from checkout.models import Sale, SaleItem

from .services import ZERO, _as_date, _salon_tz

UNCATEGORIZED_NAME = "Uncategorized"
CENTS = Decimal("0.01")


def _share(part, total):
    if not total:
        return None
    return (Decimal(part) * 100 / Decimal(total)).quantize(
        CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CategoryMix:
    """Revenue/count share for one service category in a window.

    ``category`` is the linked ``ServiceCategory`` (``None`` for
    the uncategorized snapshot-only row). Shares are Decimals or
    ``None`` when the corresponding window total is zero.
    """

    category: object | None
    category_name: str
    revenue: Decimal
    quantity: int
    line_count: int
    sale_count: int
    service_count: int
    revenue_share_percent: Decimal | None
    quantity_share_percent: Decimal | None

    @property
    def category_id(self):
        return self.category.pk if self.category is not None else None

    @property
    def name(self):
        return self.category_name

    display_name = name

    @property
    def total(self):
        return self.revenue

    @property
    def count(self):
        return self.quantity


# Aliases: the same result under other natural names.
CategoryMixRow = CategoryMix
ServiceCategoryMix = CategoryMix


def category_mix(salon, start=None, end=None, *,
                 start_date=None, end_date=None,
                 since=None, until=None):
    """Return the service-category mix for ``salon`` over a range.

    ``start`` / ``end`` are inclusive bounds (``date`` or
    ``datetime`` judged in the salon's timezone, as in
    :mod:`insights.service_revenue`); ``start_date`` / ``end_date``
    and ``since`` / ``until`` are keyword aliases. Returns
    :class:`CategoryMix` rows ranked by revenue descending; an
    empty or reversed range returns ``[]``, never ``None``.
    """
    if start is None:
        start = start_date if start_date is not None else since
    if end is None:
        end = end_date if end_date is not None else until
    if start is None or end is None:
        raise TypeError("category_mix requires a start and an end date")
    tz = _salon_tz(salon)
    start_day = _as_date(start, tz)
    end_day = _as_date(end, tz)
    if end_day < start_day:
        return []
    start_dt = datetime.combine(start_day, time.min, tzinfo=tz)
    end_dt = datetime.combine(end_day + timedelta(days=1), time.min,
                              tzinfo=tz)
    items = (
        SaleItem.objects.filter(
            sale__salon=salon, sale__status=Sale.Status.COMPLETED,
            kind=SaleItem.Kind.SERVICE,
        )
        .filter(
            Q(sale__completed_at__gte=start_dt,
              sale__completed_at__lt=end_dt)
            | Q(sale__completed_at__isnull=True,
                sale__created_at__gte=start_dt,
                sale__created_at__lt=end_dt)
        )
        .select_related("sale", "service", "service__category")
        .order_by("sale_id", "id")
    )
    # key: ("category", pk) or ("snapshot",) ->
    # [category, name, revenue, quantity, lines, {sale ids}, {svc ids}]
    buckets = {}
    for item in items:
        if item.service_id is not None and item.service is not None:
            category = item.service.category
            key = ("category", category.pk)
            name = category.name or UNCATEGORIZED_NAME
        else:
            category = None
            key = ("snapshot",)
            name = UNCATEGORIZED_NAME
        bucket = buckets.setdefault(
            key, [category, name, ZERO, 0, 0, set(), set()])
        bucket[2] += item.line_total
        bucket[3] += item.quantity
        bucket[4] += 1
        bucket[5].add(item.sale_id)
        if item.service_id is not None:
            bucket[6].add(item.service_id)
    total_revenue = sum((b[2] for b in buckets.values()), ZERO)
    total_quantity = sum(b[3] for b in buckets.values())
    rows = [
        CategoryMix(
            category=category, category_name=name, revenue=revenue,
            quantity=quantity, line_count=lines,
            sale_count=len(sale_ids), service_count=len(service_ids),
            revenue_share_percent=_share(revenue, total_revenue),
            quantity_share_percent=_share(quantity, total_quantity),
        )
        for category, name, revenue, quantity, lines, sale_ids, service_ids
        in buckets.values()
    ]
    rows.sort(key=lambda row: (-row.revenue, row.category_name))
    return rows


# Aliases: the same service under other natural names.
service_category_mix = category_mix
revenue_by_category = category_mix
get_category_mix = category_mix
