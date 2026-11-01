"""Daily sales summary service for checkout.

Backend only — no views, templates, or UI.

:func:`daily_sales_summary` answers, for one salon and one local
calendar day: how many sales were there, what was their gross
total, and how that gross splits by :class:`SaleItem` kind.

Facts and their one source of truth (nothing is stored here):

* A sale's gross is the sum of its items' line totals
  (``unit_price * quantity``) — the same derivation as
  :attr:`Sale.total`. Payments are not used for the gross: a
  payment records how a sale was settled, not what was sold, and
  pending/failed payments moved no money.
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
    ``"series"``). An empty day is all zeroes, never ``None``.
    """

    salon: object
    day: datetime.date
    sales_count: int
    gross_total: Decimal
    service_total: Decimal
    retail_total: Decimal
    series_total: Decimal = _ZERO
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

    def __getitem__(self, key):
        if key in ("service", SaleItem.Kind.SERVICE):
            return self.service_total
        if key in ("product", "retail", SaleItem.Kind.PRODUCT):
            return self.retail_total
        if key in ("series", SaleItem.Kind.SERIES):
            return self.series_total
        if key in ("gross_total", "total", "gross"):
            return self.gross_total
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
    sales_count = sales.count()

    rows = (
        SaleItem.objects.filter(sale__in=sales)
        .values("kind")
        .annotate(
            amount=Sum(F("unit_price") * F("quantity")),
            n=Count("id"),
        )
    )
    by_kind = {
        SaleItem.Kind.SERVICE: _ZERO,
        SaleItem.Kind.PRODUCT: _ZERO,
        SaleItem.Kind.SERIES: _ZERO,
    }
    item_count = 0
    for row in rows:
        item_count += row["n"]
        if row["kind"] in by_kind and row["amount"] is not None:
            by_kind[row["kind"]] = Decimal(row["amount"]).quantize(_CENTS)

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
        by_kind=dict(by_kind),
        item_count=item_count,
    )
