"""Week / month revenue rollup: daily trend, grouped.

Backend only — no views, templates, or UI. Nothing is stored.
:mod:`insights.trend` is the one source of truth for revenue; this
module never re-queries sales — it sums that service's per-day
entries verbatim, so a week/month figure reconciles EXACTLY with
the sum of its member days, service/retail/series split preserved.
Weeks are ISO weeks (Monday start, label ``YYYY-Www``); months are
calendar months (label ``YYYY-MM``). Edge buckets are partial:
``start_date``/``end_date`` are the first/last member day in the
window and ``day_count`` counts member days only.
"""
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from .services import ZERO
from .trend import daily_revenue_trend

__all__ = ["RollupPeriod", "RevenueRollupPeriod", "RollupResult",
           "RevenueRollup", "weekly_revenue_rollup",
           "monthly_revenue_rollup", "revenue_rollup",
           "get_revenue_rollup", "weekly_rollup", "monthly_rollup"]

_WEEK = ("week", "weekly", "iso_week")
_MONTH = ("month", "monthly", "calendar_month")


@dataclass(frozen=True)
class RollupPeriod:
    """Summed revenue for one ISO week or one calendar month."""

    granularity: str
    label: str
    start_date: date
    end_date: date
    service: Decimal
    retail: Decimal
    series: Decimal
    total: Decimal
    day_count: int
    days: tuple

    @property
    def period_start(self):
        return self.start_date

    @property
    def period_end(self):
        return self.end_date

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


RevenueRollupPeriod = RollupPeriod


class RollupResult(list):
    """A list of :class:`RollupPeriod`, oldest first, plus bounds."""

    def __init__(self, entries, *, start_date, end_date, days,
                 granularity):
        super().__init__(entries)
        self.start_date = start_date
        self.end_date = end_date
        self.days_requested = days
        self.granularity = granularity

    @property
    def periods(self):
        return tuple(self)

    entries = periods


RevenueRollup = RollupResult


def _bucket_key(day, granularity):
    if granularity == "week":
        iso = day.isocalendar()
        monday = day - timedelta(days=day.weekday())
        return (iso.year, iso.week, monday), f"{iso.year}-W{iso.week:02d}"
    return (day.year, day.month), f"{day.year:04d}-{day.month:02d}"


def _rollup(salon, granularity, days, end_date, today):
    if days is None:
        days = 28 if granularity == "week" else 90
    trend = daily_revenue_trend(
        salon, days=days, end_date=end_date, today=today)
    buckets = {}
    order = []
    for entry in trend:
        key, label = _bucket_key(entry.date, granularity)
        if key not in buckets:
            buckets[key] = [label, []]
            order.append(key)
        buckets[key][1].append(entry)
    periods = []
    for key in order:
        label, members = buckets[key]
        service = sum((e.service for e in members), ZERO)
        retail = sum((e.retail for e in members), ZERO)
        series = sum((e.series for e in members), ZERO)
        periods.append(RollupPeriod(
            granularity=granularity, label=label,
            start_date=members[0].date, end_date=members[-1].date,
            service=service, retail=retail, series=series,
            total=service + retail + series,
            day_count=len(members), days=tuple(members),
        ))
    return RollupResult(
        periods, start_date=trend.start_date, end_date=trend.end_date,
        days=trend.days_requested, granularity=granularity,
    )


def weekly_revenue_rollup(salon, days=28, *, end_date=None, today=None):
    """Daily trend rolled into ISO weeks; args mirror trend's.

    Window is ``days`` days (default 28) ending ``end_date``
    (alias ``today``), inclusive; edge weeks may be partial.
    """
    return _rollup(salon, "week", days, end_date, today)


def monthly_revenue_rollup(salon, days=90, *, end_date=None, today=None):
    """Daily trend rolled into calendar months (90-day default).

    Args mirror :func:`insights.trend.daily_revenue_trend`; edge
    months may be partial.
    """
    return _rollup(salon, "month", days, end_date, today)


def revenue_rollup(salon, granularity="week", days=None, *,
                   end_date=None, today=None):
    """Dispatch by ``granularity`` (week/month + aliases).

    Anything else raises ``ValueError``; ``days=None`` uses the
    chosen rollup's default window.
    """
    name = str(granularity).strip().lower()
    if name in _WEEK:
        return weekly_revenue_rollup(
            salon, days=28 if days is None else days,
            end_date=end_date, today=today)
    if name in _MONTH:
        return monthly_revenue_rollup(
            salon, days=90 if days is None else days,
            end_date=end_date, today=today)
    raise ValueError(f"Unknown granularity {granularity!r}.")


get_revenue_rollup = revenue_rollup
weekly_rollup = weekly_revenue_rollup
monthly_rollup = monthly_revenue_rollup
