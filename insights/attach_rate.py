"""Retail attach rate: how often a service sale also sells retail.

Backend only — no views, templates, or UI. Nothing is stored.

Definitions (the contract of this module)
-----------------------------------------
* A *service sale* is a completed ``Sale`` for the salon, in the
  window, carrying at least one ``SaleItem.Kind.SERVICE`` line.
  Only completed sales count — open and voided sales never do —
  exactly as in :mod:`insights.trend`. A sale belongs to the day
  of its ``completed_at`` when set, otherwise its ``created_at``,
  judged in the salon's timezone.
* A service sale is *attached* when it also carries at least one
  ``SaleItem.Kind.PRODUCT`` line (retail is the insights name for
  product sales, as in :mod:`insights.services`).
* ``attach_rate`` is ``attached_sales / service_sales`` as a
  Decimal in [0, 1] (0 when there are no service sales), and
  ``attach_rate_percent`` is the same figure x100.
* ``retail_revenue`` sums PRODUCT ``line_total``s on service
  sales only (so it reconciles with attached sales);
  ``retail_revenue_per_service_sale`` is that sum divided by
  ``service_sales`` and ``retail_revenue_per_attached_sale`` by
  ``attached_sales`` (both 0.00 when the divisor is 0).
  ``total_retail_revenue`` counts PRODUCT lines on every
  completed sale in the window, including product-only sales.
* Series lines neither make a sale a service sale nor attach it.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from checkout.models import Sale, SaleItem

from .services import ZERO, _salon_tz

__all__ = ["AttachDay", "AttachRateDay", "RetailAttachRate",
           "AttachRateResult", "retail_attach_rate",
           "get_retail_attach_rate", "attach_rate"]

_RATE = Decimal("0.0001")
_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class AttachDay:
    """Attach figures for one calendar day."""

    date: date
    service_sales: int
    attached_sales: int
    retail_revenue: Decimal
    service_revenue: Decimal

    @property
    def day(self):
        return self.date

    @property
    def attach_rate(self):
        if not self.service_sales:
            return Decimal("0.0000")
        return (Decimal(self.attached_sales)
                / self.service_sales).quantize(
                    _RATE, rounding=ROUND_HALF_UP)


AttachRateDay = AttachDay


@dataclass(frozen=True)
class RetailAttachRate:
    """Retail attach figures for one inclusive window."""

    start_date: date
    end_date: date
    days: int
    service_sales: int
    attached_sales: int
    unattached_service_sales: int
    product_only_sales: int
    total_completed_sales: int
    service_revenue: Decimal
    retail_revenue: Decimal
    total_retail_revenue: Decimal
    retail_quantity: int
    daily: tuple = ()

    @property
    def attach_rate(self):
        if not self.service_sales:
            return Decimal("0.0000")
        return (Decimal(self.attached_sales)
                / self.service_sales).quantize(
                    _RATE, rounding=ROUND_HALF_UP)

    @property
    def attach_rate_percent(self):
        return (self.attach_rate * 100).quantize(
            _CENTS, rounding=ROUND_HALF_UP)

    @property
    def retail_revenue_per_service_sale(self):
        if not self.service_sales:
            return Decimal("0.00")
        return (self.retail_revenue / self.service_sales).quantize(
            _CENTS, rounding=ROUND_HALF_UP)

    @property
    def retail_revenue_per_attached_sale(self):
        if not self.attached_sales:
            return Decimal("0.00")
        return (self.retail_revenue / self.attached_sales).quantize(
            _CENTS, rounding=ROUND_HALF_UP)

    # Aliases under other natural names.
    @property
    def service_sale_count(self):
        return self.service_sales

    @property
    def attached_sale_count(self):
        return self.attached_sales

    @property
    def days_tuple(self):
        return self.daily


AttachRateResult = RetailAttachRate


def retail_attach_rate(salon, days=28, *, end_date=None, today=None):
    """Return the retail attach rate for ``salon`` over a window.

    The window is ``days`` calendar days (default 28) ending on
    ``end_date`` (alias ``today``), inclusive, as in
    :func:`insights.trend.daily_revenue_trend`. ``days <= 0``
    returns a zeroed result over an empty window.
    """
    if end_date is None:
        end_date = today
    if end_date is None:
        end_date = timezone.localdate()
    elif isinstance(end_date, datetime):
        end_date = end_date.date()
    if days is None:
        days = 28
    days = int(days)
    if days <= 0:
        return RetailAttachRate(
            start_date=end_date, end_date=end_date, days=days,
            service_sales=0, attached_sales=0,
            unattached_service_sales=0, product_only_sales=0,
            total_completed_sales=0, service_revenue=ZERO,
            retail_revenue=ZERO, total_retail_revenue=ZERO,
            retail_quantity=0, daily=())
    start_date = end_date - timedelta(days=days - 1)
    tz = _salon_tz(salon)
    start_dt = datetime.combine(start_date, time.min, tzinfo=tz)
    end_dt = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=tz)
    sales = (
        Sale.objects.filter(salon=salon, status=Sale.Status.COMPLETED)
        .filter(
            Q(completed_at__gte=start_dt, completed_at__lt=end_dt)
            | Q(completed_at__isnull=True,
                created_at__gte=start_dt, created_at__lt=end_dt))
        .prefetch_related("items").order_by("pk")
    )
    per_day = {}
    service_sales = attached = product_only = total_sales = 0
    service_rev = retail_rev = total_retail = ZERO
    retail_qty = 0
    for sale in sales:
        total_sales += 1
        svc = ZERO
        ret = ZERO
        qty = 0
        has_svc = has_ret = False
        for item in sale.items.all():
            if item.kind == SaleItem.Kind.SERVICE:
                has_svc = True
                svc += item.line_total
            elif item.kind == SaleItem.Kind.PRODUCT:
                has_ret = True
                ret += item.line_total
                qty += item.quantity
        total_retail += ret if has_ret else ZERO
        if not has_svc:
            if has_ret:
                product_only += 1
            continue
        service_sales += 1
        service_rev += svc
        stamp = sale.completed_at or sale.created_at
        day = stamp.astimezone(tz).date() if stamp else start_date
        d_svc, d_att, d_ret, d_srev = per_day.get(
            day, (0, 0, ZERO, ZERO))
        d_svc += 1
        d_srev += svc
        if has_ret:
            attached += 1
            retail_rev += ret
            retail_qty += qty
            d_att += 1
            d_ret += ret
        per_day[day] = (d_svc, d_att, d_ret, d_srev)
    daily = tuple(
        AttachDay(
            date=start_date + timedelta(days=offset),
            service_sales=per_day.get(
                start_date + timedelta(days=offset), (0, 0, ZERO, ZERO))[0],
            attached_sales=per_day.get(
                start_date + timedelta(days=offset), (0, 0, ZERO, ZERO))[1],
            retail_revenue=per_day.get(
                start_date + timedelta(days=offset), (0, 0, ZERO, ZERO))[2],
            service_revenue=per_day.get(
                start_date + timedelta(days=offset), (0, 0, ZERO, ZERO))[3],
        )
        for offset in range(days)
    )
    return RetailAttachRate(
        start_date=start_date, end_date=end_date, days=days,
        service_sales=service_sales, attached_sales=attached,
        unattached_service_sales=service_sales - attached,
        product_only_sales=product_only,
        total_completed_sales=total_sales,
        service_revenue=service_rev, retail_revenue=retail_rev,
        total_retail_revenue=total_retail,
        retail_quantity=retail_qty, daily=daily)


get_retail_attach_rate = retail_attach_rate
attach_rate = retail_attach_rate
