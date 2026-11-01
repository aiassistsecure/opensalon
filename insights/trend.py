"""Daily revenue trend: per-day revenue with a 7-day moving average.

Backend only — no views, templates, or UI. Nothing here is stored:
each figure is computed from the ``Sale`` / ``SaleItem`` rows that
own the fact, exactly as in :mod:`insights.services`.

Revenue rule (reused from
:func:`insights.services.last_7_days_revenue_split`): only
completed sales count as revenue — voided sales never count, and
open sales are not revenue yet. A sale belongs to the day of its
``completed_at`` when set, otherwise its ``created_at``, judged in
the salon's timezone. ``service`` sums ``SaleItem.Kind.SERVICE``
line totals, ``retail`` sums ``SaleItem.Kind.PRODUCT`` line totals,
``series`` sums ``SaleItem.Kind.SERIES`` line totals, and ``total``
is their sum — the same split as
:func:`insights.services.last_7_days_revenue_split`.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from checkout.models import Sale, SaleItem

from .services import ZERO, _salon_tz

CENTS = Decimal("0.01")


@dataclass(frozen=True)
class TrendDay:
    """Revenue for one calendar day, plus its trailing average.

    ``moving_average_7d`` is the simple moving average of ``total``
    over the trailing window of up to 7 days ending on this day,
    within the returned trend: the first days average over the days
    available so far (1 day on the first entry, 2 on the second,
    and the full 7 from the seventh entry onward), rounded to cents.
    """

    date: date
    service: Decimal
    retail: Decimal
    series: Decimal
    total: Decimal
    moving_average_7d: Decimal

    @property
    def day(self):
        return self.date

    @property
    def service_revenue(self):
        return self.service

    @property
    def retail_revenue(self):
        return self.retail

    @property
    def series_revenue(self):
        return self.series

    @property
    def total_revenue(self):
        return self.total

    @property
    def moving_average(self):
        return self.moving_average_7d


# Aliases: the same per-day entry under other natural names.
DailyRevenue = TrendDay
RevenueTrendDay = TrendDay


class RevenueTrend(list):
    """A list of :class:`TrendDay`, oldest first, plus window bounds.

    Behaves as a plain list (indexing, ``len``, iteration) and also
    exposes ``days`` (a tuple of the same entries), ``start_date``,
    and ``end_date`` for callers that prefer a result object.
    """

    def __init__(self, entries, *, start_date, end_date, days):
        super().__init__(entries)
        self.start_date = start_date
        self.end_date = end_date
        self.days_requested = days

    @property
    def days(self):
        return tuple(self)

    @property
    def entries(self):
        return tuple(self)


def daily_revenue_trend(salon, days=14, *, end_date=None, today=None):
    """Return the daily revenue trend for ``salon``.

    The window is ``days`` calendar days (default 14) ending on
    ``end_date`` (alias ``today``), inclusive at both ends. The
    default end date is ``timezone.localdate()`` — today in the
    salon-local (deployment) timezone. Sale days themselves are
    judged in the salon's own timezone, as in
    :mod:`insights.services`.

    Returns a :class:`RevenueTrend` of :class:`TrendDay` entries,
    one per day, oldest first, zero-filled for days with no
    qualifying sales — a salon with no sales gets all zeroes, never
    ``None``. ``days <= 0`` returns an empty trend.
    """
    if end_date is None:
        end_date = today
    if end_date is None:
        end_date = timezone.localdate()
    elif isinstance(end_date, datetime):
        end_date = end_date.date()
    if days is None:
        days = 14
    days = int(days)
    if days <= 0:
        return RevenueTrend(
            [], start_date=end_date, end_date=end_date, days=days,
        )
    start_date = end_date - timedelta(days=days - 1)

    tz = _salon_tz(salon)
    start_dt = datetime.combine(start_date, time.min, tzinfo=tz)
    end_dt = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=tz
    )
    items = (
        SaleItem.objects.filter(
            sale__salon=salon, sale__status=Sale.Status.COMPLETED,
        )
        .filter(
            Q(sale__completed_at__gte=start_dt,
              sale__completed_at__lt=end_dt)
            | Q(sale__completed_at__isnull=True,
                sale__created_at__gte=start_dt,
                sale__created_at__lt=end_dt)
        )
        .select_related("sale")
    )
    service_by_day = {}
    retail_by_day = {}
    series_by_day = {}
    for item in items:
        stamp = item.sale.completed_at or item.sale.created_at
        if stamp is None:
            continue
        day = stamp.astimezone(tz).date()
        if item.kind == SaleItem.Kind.SERVICE:
            bucket = service_by_day
        elif item.kind == SaleItem.Kind.PRODUCT:
            bucket = retail_by_day
        elif item.kind == SaleItem.Kind.SERIES:
            bucket = series_by_day
        else:
            continue
        bucket[day] = bucket.get(day, ZERO) + item.line_total

    entries = []
    trailing = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        service = service_by_day.get(day, ZERO)
        retail = retail_by_day.get(day, ZERO)
        series = series_by_day.get(day, ZERO)
        total = service + retail + series
        trailing.append(total)
        if len(trailing) > 7:
            trailing.pop(0)
        average = (sum(trailing, ZERO) / len(trailing)).quantize(
            CENTS, rounding=ROUND_HALF_UP
        )
        entries.append(TrendDay(
            date=day, service=service, retail=retail, series=series,
            total=total, moving_average_7d=average,
        ))
    return RevenueTrend(
        entries, start_date=start_date, end_date=end_date, days=days,
    )


# Aliases: the same service under other natural names.
revenue_trend = daily_revenue_trend
get_daily_revenue_trend = daily_revenue_trend
