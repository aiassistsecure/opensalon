"""Daily sales summary service for checkout.

Backend only — no views, templates, or UI.

:func:`daily_sales_summary` answers, for one salon and one local
calendar day: how many sales were there, what was their gross
total, and how that gross splits by :class:`SaleItem` kind.

Facts and their one source of truth (nothing is stored here):

* A sale's gross is the sum of its items' pre-discount line
  amounts (``unit_price * quantity``) — the same derivation as
  :attr:`Sale.subtotal`. Payments are not used for the gross: a
  payment records how a sale was settled, not what was sold, and
  pending/failed payments moved no money.
* Discounts are reported, never netted silently: ``discount_total``
  is every recorded discount for the day (per-line
  ``SaleItem.discount_amount`` plus each sale's own
  ``Sale.discount_amount``), and ``net_total`` is
  ``gross_total - discount_total`` — the day's equivalent of
  :attr:`Sale.total` summed over its sales. The kind split stays
  gross, exactly as before.
* The kind split uses the model's real kinds: ``SERVICE`` items
  are the service total, ``PRODUCT`` items are the retail
  total (``retail`` is the reporting name for product sales, as
  in :mod:`insights.services`), and ``SERIES`` items are the
  series total — the same three-way split as
  :class:`insights.services.RevenueSplit`. The gross is the sum
  of all three, so a sale containing series lines is never
  understated.
* Voided sales are excluded entirely — count, gross, and split.
  ``Sale.Status`` has no cancelled value, so voided is the only
  exclusion; every other status (open and completed) counts.
* A sale belongs to the day of its ``completed_at`` when set,
  otherwise its ``created_at`` — the attribution the insights
  services already use — judged in the salon's timezone
  (``Salon.timezone``, falling back to UTC).

Core stays provider-agnostic: no payment-provider SDK, field, or
name appears here.
"""
import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Count, F, Q, Sum

from .models import Sale, SaleItem

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class DailySalesSummary:
    """One salon's sales for one local calendar day.

    ``sales_count`` is the number of non-voided sales attributed
    to ``day``; ``gross_total`` is the sum of their item line
    totals; ``service_total`` / ``retail_total`` / ``series_total``
    are the gross split by item kind (service vs product/retail
    vs series), and ``by_kind`` carries the same split keyed by
    the model's kind slugs (``"service"`` / ``"product"`` /
    ``"series"``). ``discount_total`` is every discount recorded
    on those sales and their lines; ``net_total`` is gross less
    discounts. An empty day is all zeroes, never ``None``.
    """

    salon: object
    day: datetime.date
    sales_count: int
    gross_total: Decimal
    service_total: Decimal
    retail_total: Decimal
    series_total: Decimal = _ZERO
    discount_total: Decimal = _ZERO
    net_total: Decimal = _ZERO
    by_kind: dict = field(default_factory=dict)
    item_count: int = 0

    @property
    def date(self):
        return self.day

    @property
    def salon_id(self):
        return getattr(self.salon, "pk", self.salon)

    @property
    def count(self):
        return self.sales_count

    @property
    def total_sales(self):
        return self.sales_count

    @property
    def sale_count(self):
        return self.sales_count

    @property
    def total(self):
        return self.gross_total

    @property
    def gross(self):
        return self.gross_total

    @property
    def service(self):
        return self.service_total

    @property
    def services_total(self):
        return self.service_total

    @property
    def retail(self):
        return self.retail_total

    @property
    def product_total(self):
        return self.retail_total

    @property
    def product(self):
        return self.retail_total

    @property
    def series(self):
        return self.series_total

    @property
    def series_revenue(self):
        return self.series_total

    @property
    def discount(self):
        return self.discount_total

    @property
    def discounts_total(self):
        return self.discount_total

    @property
    def net(self):
        return self.net_total

    def __getitem__(self, key):
        if key in ("service", SaleItem.Kind.SERVICE):
            return self.service_total
        if key in ("product", "retail", SaleItem.Kind.PRODUCT):
            return self.retail_total
        if key in ("series", SaleItem.Kind.SERIES):
            return self.series_total
        if key in ("gross_total", "total", "gross"):
            return self.gross_total
        if key in ("discount_total", "discount", "discounts_total"):
            return self.discount_total
        if key in ("net_total", "net"):
            return self.net_total
        if key in ("sales_count", "count", "total_sales"):
            return self.sales_count
        return self.by_kind[key]


def _salon_tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_day(day, tz):
    if isinstance(day, datetime.datetime):
        if day.tzinfo is not None:
            return day.astimezone(tz).date()
        return day.date()
    if isinstance(day, datetime.date):
        return day
    raise ValueError("daily_sales_summary needs a date for `day`")


def daily_sales_summary(salon, day):
    """Return the :class:`DailySalesSummary` for ``salon`` on ``day``.

    ``day`` is a ``date`` (or a ``datetime``, judged by its date
    in the salon's timezone) naming one local calendar day in the
    salon's timezone. Only that salon's sales count — sales of
    every other salon are excluded, however they interleave in
    time. Voided sales are excluded. Read-only: nothing is
    created, updated, or deleted.
    """
    if salon is None:
        raise ValueError("daily_sales_summary needs a salon")
    tz = _salon_tz(salon)
    local_day = _as_day(day, tz)
    start_dt = datetime.datetime.combine(
        local_day, datetime.time.min, tzinfo=tz
    )
    end_dt = start_dt + datetime.timedelta(days=1)

    sales = Sale.objects.filter(salon=salon).exclude(
        status=Sale.Status.VOIDED
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lt=end_dt)
        | Q(
            completed_at__isnull=True,
            created_at__gte=start_dt,
            created_at__lt=end_dt,
        )
    )
    sale_ids = list(sales.values_list("id", flat=True))
    sales_count = len(sale_ids)

    rows = (
        SaleItem.objects.filter(sale_id__in=sale_ids)
        .values("kind")
        .annotate(
            amount=Sum(F("unit_price") * F("quantity")),
            discount=Sum("discount_amount"),
            n=Count("id"),
        )
    )
    by_kind = {
        SaleItem.Kind.SERVICE: _ZERO,
        SaleItem.Kind.PRODUCT: _ZERO,
        SaleItem.Kind.SERIES: _ZERO,
    }
    item_count = 0
    item_discount_total = _ZERO
    for row in rows:
        item_count += row["n"]
        if row["discount"] is not None:
            item_discount_total += Decimal(row["discount"])
        if row["kind"] in by_kind and row["amount"] is not None:
            by_kind[row["kind"]] = Decimal(row["amount"]).quantize(_CENTS)

    sale_discount = sales.aggregate(amount=Sum("discount_amount"))["amount"]
    discount_total = (
        item_discount_total
        + (Decimal(sale_discount) if sale_discount is not None else _ZERO)
    ).quantize(_CENTS)

    service_total = by_kind[SaleItem.Kind.SERVICE]
    retail_total = by_kind[SaleItem.Kind.PRODUCT]
    series_total = by_kind[SaleItem.Kind.SERIES]
    gross_total = (service_total + retail_total + series_total).quantize(_CENTS)
    return DailySalesSummary(
        salon=salon,
        day=local_day,
        sales_count=sales_count,
        gross_total=gross_total,
        service_total=service_total,
        retail_total=retail_total,
        series_total=series_total,
        discount_total=discount_total,
        net_total=(gross_total - discount_total).quantize(_CENTS),
        by_kind=dict(by_kind),
        item_count=item_count,
    )


def daily_sales_summaries(salon, start, end):
    """Return one :class:`DailySalesSummary` per day in a range.

    The range version of :func:`daily_sales_summary`: a list with
    exactly one entry for every local calendar day from ``start``
    to ``end`` inclusive (empty days included, all zeroes), each
    entry exactly equal to ``daily_sales_summary(salon, that_day)``
    — same date rule, same voided exclusion, same salon scoping,
    same quantization. It reads the whole range in two queries
    (one over the range's sales, one over their items grouped by
    sale and kind) and buckets by each sale's local day in Python,
    so a long range costs no more round trips than a short one.
    Read-only: nothing is created, updated, or deleted.
    """
    if salon is None:
        raise ValueError("daily_sales_summaries needs a salon")
    tz = _salon_tz(salon)
    first_day = _as_day(start, tz)
    last_day = _as_day(end, tz)
    if last_day < first_day:
        return []
    days = []
    day = first_day
    while day <= last_day:
        days.append(day)
        day += datetime.timedelta(days=1)
    range_start = datetime.datetime.combine(
        first_day, datetime.time.min, tzinfo=tz
    )
    range_end = range_start + datetime.timedelta(days=len(days))

    sale_rows = (
        Sale.objects.filter(salon=salon)
        .exclude(status=Sale.Status.VOIDED)
        .filter(
            Q(completed_at__gte=range_start, completed_at__lt=range_end)
            | Q(
                completed_at__isnull=True,
                created_at__gte=range_start,
                created_at__lt=range_end,
            )
        )
        .values("id", "completed_at", "created_at", "discount_amount")
    )
    sale_day = {}
    day_sales = {
        d: {"count": 0, "discount": _ZERO} for d in days
    }
    for row in sale_rows:
        stamp = (
            row["completed_at"]
            if row["completed_at"] is not None
            else row["created_at"]
        )
        if stamp.tzinfo is not None:
            local_day = stamp.astimezone(tz).date()
        else:
            local_day = stamp.date()
        sale_day[row["id"]] = local_day
        bucket = day_sales[local_day]
        bucket["count"] += 1
        if row["discount_amount"] is not None:
            bucket["discount"] += Decimal(row["discount_amount"])

    item_rows = (
        SaleItem.objects.filter(sale_id__in=list(sale_day))
        .values("sale_id", "kind")
        .annotate(
            amount=Sum(F("unit_price") * F("quantity")),
            discount=Sum("discount_amount"),
            n=Count("id"),
        )
    )
    day_items = {
        d: {
            "by_kind": {
                SaleItem.Kind.SERVICE: _ZERO,
                SaleItem.Kind.PRODUCT: _ZERO,
                SaleItem.Kind.SERIES: _ZERO,
            },
            "count": 0,
            "discount": _ZERO,
        }
        for d in days
    }
    for row in item_rows:
        bucket = day_items[sale_day[row["sale_id"]]]
        bucket["count"] += row["n"]
        if row["discount"] is not None:
            bucket["discount"] += Decimal(row["discount"])
        if row["kind"] in bucket["by_kind"] and row["amount"] is not None:
            bucket["by_kind"][row["kind"]] += Decimal(row["amount"])

    summaries = []
    for d in days:
        by_kind = {
            kind: amount.quantize(_CENTS)
            for kind, amount in day_items[d]["by_kind"].items()
        }
        discount_total = (
            day_items[d]["discount"] + day_sales[d]["discount"]
        ).quantize(_CENTS)
        service_total = by_kind[SaleItem.Kind.SERVICE]
        retail_total = by_kind[SaleItem.Kind.PRODUCT]
        series_total = by_kind[SaleItem.Kind.SERIES]
        gross_total = (
            service_total + retail_total + series_total
        ).quantize(_CENTS)
        summaries.append(
            DailySalesSummary(
                salon=salon,
                day=d,
                sales_count=day_sales[d]["count"],
                gross_total=gross_total,
                service_total=service_total,
                retail_total=retail_total,
                series_total=series_total,
                discount_total=discount_total,
                net_total=(gross_total - discount_total).quantize(_CENTS),
                by_kind=by_kind,
                item_count=day_items[d]["count"],
            )
        )
    return summaries
