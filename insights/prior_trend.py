"""Prior-period comparison for the daily revenue trend.

Backend only — no views, templates, or UI. Nothing is stored.
Mirrors :mod:`insights.prior_busiest`: the prior period is the
equal-length window immediately before the current one, and
each window's figures come verbatim from
:func:`insights.trend.daily_revenue_trend` — never re-derived
from ``Sale`` rows (this wrapper counts nothing itself; it
calls the trend twice).

Comparison is OFFSET-ALIGNED by day position within the window
(day 1 vs day 1, day 2 vs day 2, …): per-day ``service`` /
``retail`` / ``series`` / ``total`` deltas, plus each day's
``moving_average_7d`` carried as the source's verbatim
current/prior pair with its delta (via the shared
:class:`~insights.prior_period.ComponentDelta`, so
``percent_change`` is a Decimal quantised to two places,
``None`` when the prior figure is zero; the ``delta`` is
always present). Both windows are stored Sale rows, so the
comparison is honest with no as-of claim. A reversed window
raises ``ValueError``.
"""
from dataclasses import dataclass
from datetime import timedelta

from .prior_period import ComponentDelta, _as_window_date, _delta
from .trend import TrendDay, daily_revenue_trend

__all__ = [
    "TrendDayDelta", "PriorTrendComparison", "prior_trend",
    "prior_period_trend", "compare_trend", "get_prior_trend",
    "prior_trend_comparison",
]

_FIELDS = ("service", "retail", "series", "total", "moving_average_7d")


@dataclass(frozen=True)
class TrendDayDelta:
    """One offset-aligned per-day pair: current day vs prior day."""

    offset: int
    current: TrendDay
    prior: TrendDay
    service: ComponentDelta
    retail: ComponentDelta
    series: ComponentDelta
    total: ComponentDelta
    moving_average_7d: ComponentDelta

    @property
    def previous(self): return self.prior
    @property
    def date(self): return self.current.date
    @property
    def current_date(self): return self.current.date
    @property
    def prior_date(self): return self.prior.date
    @property
    def moving_average(self): return self.moving_average_7d
    @property
    def deltas(self):
        return {name: getattr(self, name) for name in _FIELDS}


@dataclass(frozen=True)
class PriorTrendComparison:
    """Current vs prior daily trend, offset-aligned per day."""

    current: tuple
    prior: tuple
    per_day: tuple
    start: object
    end: object
    prior_start: object
    prior_end: object

    @property
    def previous(self): return self.prior
    @property
    def start_date(self): return self.start
    @property
    def end_date(self): return self.end
    @property
    def prior_start_date(self): return self.prior_start
    @property
    def prior_end_date(self): return self.prior_end
    @property
    def days(self): return (self.end - self.start).days + 1
    @property
    def entries(self): return self.per_day
    @property
    def by_day(self): return self.per_day
    @property
    def by_offset(self): return {r.offset: r for r in self.per_day}


def prior_trend(salon, start_date=None, end_date=None, **kwargs):
    """Return the daily-trend comparison for ``salon``.

    ``start_date`` / ``end_date`` are the inclusive current
    window (``date``, ``datetime``, or ISO string; ``start`` /
    ``end`` and ``since`` / ``until`` are accepted as keyword
    aliases), as in :mod:`insights.prior_period`. See the
    module docstring for the prior-window, offset-alignment,
    moving-average, and zero-prior rules.
    """
    if salon is None:
        raise ValueError("prior_trend needs a salon")
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
    prior_end = start - timedelta(days=1)
    prior_start = start - timedelta(days=length)
    current = daily_revenue_trend(salon, days=length, end_date=end)
    prior = daily_revenue_trend(salon, days=length, end_date=prior_end)
    per_day = tuple(
        TrendDayDelta(
            offset=offset, current=cur, prior=pri,
            **{name: _delta(name, getattr(cur, name), getattr(pri, name))
               for name in _FIELDS})
        for offset, (cur, pri) in enumerate(zip(current, prior)))
    return PriorTrendComparison(
        current=tuple(current), prior=tuple(prior), per_day=per_day,
        start=start, end=end, prior_start=prior_start, prior_end=prior_end)


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_trend = prior_trend
compare_trend = prior_trend
get_prior_trend = prior_trend
prior_trend_comparison = prior_trend
