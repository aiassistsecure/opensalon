"""Prior-period comparison for busiest days.

Backend only — no views, templates, or UI. Nothing is stored.
Mirrors :mod:`insights.prior_discounts`: the prior period is
the equal-length window immediately before the current one,
and each window's figures come verbatim from
:func:`insights.services.busiest_days` — never re-derived.

Comparison is keyed BY WEEKDAY (Monday=0 through Sunday=6),
never by rank position: ``busiest_days`` orders rows by count
descending and that rank may legitimately differ between
windows, so rows are matched on ``weekday`` alone and returned
in weekday order. Whole-week windows (length a multiple of
seven days) make per-weekday counts exactly comparable, since
every weekday then occurs equally often in each window; that
is the intended use. ``percent_change`` is a Decimal quantised
to two places, ``None`` when the prior figure is zero (the
``delta`` is always present); a reversed window raises
``ValueError``. Counts are compared as Decimals via
``Decimal(int)`` (house convention, cf.
:mod:`insights.prior_retention_returning`); the verbatim rows
on ``current``/``prior`` keep their integer counts.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .prior_period import ComponentDelta, _as_window_date, _delta
from .services import BusiestDay, WEEKDAY_NAMES, busiest_days

__all__ = [
    "BusiestWeekdayDelta", "PriorBusiestComparison", "prior_busiest",
    "prior_period_busiest", "compare_busiest", "get_prior_busiest",
]


def _count_delta(component, current, prior):
    return _delta(component, Decimal(current), Decimal(prior))


@dataclass(frozen=True)
class BusiestWeekdayDelta:
    """One weekday's busiest-day figures in both periods."""

    weekday: int
    weekday_name: str
    current: BusiestDay
    prior: BusiestDay
    count: ComponentDelta
    appointment_value: ComponentDelta
    revenue: ComponentDelta

    @property
    def previous(self): return self.prior
    @property
    def deltas(self):
        return {"count": self.count,
                "appointment_value": self.appointment_value,
                "revenue": self.revenue}


@dataclass(frozen=True)
class PriorBusiestComparison:
    """Current vs prior busiest-days rows, keyed by weekday."""

    current: tuple
    prior: tuple
    weekdays: tuple
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
    def by_weekday(self): return {r.weekday: r for r in self.weekdays}
    @property
    def deltas(self): return self.by_weekday


def prior_busiest(salon, start_date=None, end_date=None, **kwargs):
    """Return the busiest-days comparison for ``salon``.

    ``start_date`` / ``end_date`` are the inclusive current
    window (``date``, ``datetime``, or ISO string; ``start`` /
    ``end`` and ``since`` / ``until`` are accepted as keyword
    aliases), as in :mod:`insights.prior_period`. See the
    module docstring for the prior-window, weekday-keying,
    whole-week, and zero-prior rules.
    """
    if salon is None:
        raise ValueError("prior_busiest needs a salon")
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
    current = busiest_days(salon, start, end)
    prior = busiest_days(salon, prior_start, prior_end)
    cur = {e.weekday: e for e in current}
    pri = {e.weekday: e for e in prior}
    weekdays = tuple(
        BusiestWeekdayDelta(
            weekday=w, weekday_name=WEEKDAY_NAMES[w],
            current=cur[w], prior=pri[w],
            count=_count_delta("count", cur[w].count, pri[w].count),
            appointment_value=_delta(
                "appointment_value", cur[w].appointment_value,
                pri[w].appointment_value),
            revenue=_delta("revenue", cur[w].revenue, pri[w].revenue),
        ) for w in range(7))
    return PriorBusiestComparison(
        current=tuple(current), prior=tuple(prior), weekdays=weekdays,
        start=start, end=end, prior_start=prior_start, prior_end=prior_end)


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_busiest = prior_busiest
compare_busiest = prior_busiest
get_prior_busiest = prior_busiest
