"""Insights service functions: figures derived from checkout sales.

Backend only — no views, templates, or UI. Nothing here is stored:
each figure is computed from ``Sale`` / ``SaleItem`` rows, which
remain the one source of truth for revenue.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import F, Sum
from django.utils import timezone

from checkout.models import Sale, SaleItem

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class RevenueSplit:
    """Revenue for one inclusive date window, split by item kind.

    ``service`` sums line totals of ``SaleItem.Kind.SERVICE`` items,
    ``retail`` sums ``SaleItem.Kind.PRODUCT`` items (retail is the
    insights name for product sales), and ``total`` is their sum.
    ``start_date`` / ``end_date`` are the inclusive window bounds in
    the salon's timezone.
    """

    service: Decimal
    retail: Decimal
    total: Decimal
    start_date: date
    end_date: date
    days: int = 7


def _salon_tz(salon):
    try:
        return ZoneInfo(salon.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def last_7_days_revenue_split(salon, *, today=None):
    """Return the last 7 days' revenue split for ``salon``.

    The window is the 7 calendar days ending on ``today`` (default:
    today in the salon's timezone), inclusive at both ends, judged
    in the salon's timezone. Only completed sales count as revenue:
    open and voided sales are excluded. A sale belongs to the day of
    its ``completed_at`` when set, otherwise its ``created_at``.

    Returns a :class:`RevenueSplit` with Decimal amounts; a salon
    with no qualifying sales gets zeroes, never None.
    """
    tz = _salon_tz(salon)
    if today is None:
        today = timezone.now().astimezone(tz).date()
    start_date = today - timedelta(days=6)

    items = SaleItem.objects.filter(
        sale__salon=salon,
        sale__status=Sale.Status.COMPLETED,
    )
    totals = {SaleItem.Kind.SERVICE: ZERO, SaleItem.Kind.PRODUCT: ZERO}
    start_dt = datetime.combine(start_date, time.min, tzinfo=tz)
    end_dt = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
    in_window = items.filter(
        sale__completed_at__gte=start_dt,
        sale__completed_at__lt=end_dt,
    ) | items.filter(
        sale__completed_at__isnull=True,
        sale__created_at__gte=start_dt,
        sale__created_at__lt=end_dt,
    )
    rows = in_window.values("kind").annotate(
        amount=Sum(F("unit_price") * F("quantity"))
    )
    for row in rows:
        if row["kind"] in totals and row["amount"] is not None:
            totals[row["kind"]] = row["amount"]

    service = totals[SaleItem.Kind.SERVICE]
    retail = totals[SaleItem.Kind.PRODUCT]
    return RevenueSplit(
        service=service,
        retail=retail,
        total=service + retail,
        start_date=start_date,
        end_date=today,
        days=7,
    )
