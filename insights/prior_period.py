"""Prior-period comparison for the revenue split (and trend totals).

Backend only — no views, templates, or UI. Nothing here is stored:
each figure is computed from the existing insights services, which
remain the one source of truth for what revenue is.

Definition
----------
For an inclusive current window ``[start_date, end_date]`` of
``length = (end_date - start_date).days + 1`` days, the prior
period is the immediately preceding window of equal length:
``[start_date - length, start_date - 1 day]``.

Splits are never re-derived from ``Sale`` rows here. A 7-day
window reuses :func:`insights.services.last_7_days_revenue_split`
verbatim; any other length sums the per-day entries of
:func:`insights.trend.daily_revenue_trend` (which itself applies
the same revenue rule) into a :class:`insights.services.RevenueSplit`.
That sum is the window's trend total, so the split comparison and
the trend comparison can never disagree.

Percentage change
-----------------
``percent_change`` is ``(current - prior) / prior * 100`` as a
:class:`~decimal.Decimal` quantised to two places (``25.00``
means +25%). When the prior component is zero there is no
meaningful percentage, so the documented sentinel is ``None``
— never a division error, never infinity. The absolute
``delta`` (``current - prior``, a Decimal) is always present.
A reversed window (``end_date`` before ``start_date``) raises
``ValueError``.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .services import ZERO, RevenueSplit, _salon_tz, last_7_days_revenue_split
from .trend import daily_revenue_trend

__all__ = [
    "ComponentDelta",
    "PriorPeriodComparison",
    "prior_period_revenue_split",
    "prior_period_comparison",
    "compare_revenue_split",
    "get_prior_period_comparison",
]

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class ComponentDelta:
    """One revenue component in both periods, with its change."""

    component: str
    current: Decimal
    prior: Decimal
    delta: Decimal
    percent_change: Decimal | None

    @property
    def previous(self):
        return self.prior

    @property
    def change(self):
        return self.delta

    @property
    def pct_change(self):
        return self.percent_change


@dataclass(frozen=True)
class PriorPeriodComparison:
    """Current vs prior :class:`RevenueSplit`, plus per-component deltas."""

    current: RevenueSplit
    prior: RevenueSplit
    service: ComponentDelta
    retail: ComponentDelta
    series: ComponentDelta
    total: ComponentDelta

    @property
    def previous(self):
        return self.prior

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

    @property
    def deltas(self):
        return {
            "service": self.service, "retail": self.retail,
            "series": self.series, "total": self.total,
        }


def _as_window_date(value, salon):
    if isinstance(value, datetime):
        return value.astimezone(_salon_tz(salon)).date() \
            if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _split_for_window(salon, start_date, end_date):
    length = (end_date - start_date).days + 1
    if length == 7:
        return last_7_days_revenue_split(salon, today=end_date)
    trend = daily_revenue_trend(salon, days=length, end_date=end_date)
    service = sum((e.service for e in trend), ZERO)
    retail = sum((e.retail for e in trend), ZERO)
    series = sum((e.series for e in trend), ZERO)
    return RevenueSplit(
        service=service, retail=retail, series=series,
        total=service + retail + series,
        start_date=start_date, end_date=end_date, days=length,
    )


def _delta(component, current, prior):
    if prior == ZERO:
        pct = None
    else:
        pct = ((current - prior) / prior * 100).quantize(
            _CENTS, rounding=ROUND_HALF_UP
        )
    return ComponentDelta(
        component=component, current=current, prior=prior,
        delta=current - prior, percent_change=pct,
    )


def prior_period_revenue_split(salon, start_date=None, end_date=None, **kwargs):
    """Return the prior-period comparison for ``salon``.

    ``start_date`` / ``end_date`` are the inclusive current window
    (``date``, ``datetime``, or ISO string; ``start`` / ``end`` and
    ``since`` / ``until`` are accepted as keyword aliases). See the
    module docstring for the prior-window and zero-prior rules.
    """
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
    current = _split_for_window(salon, start, end)
    prior = _split_for_window(salon, prior_start, prior_end)
    return PriorPeriodComparison(
        current=current, prior=prior,
        service=_delta("service", current.service, prior.service),
        retail=_delta("retail", current.retail, prior.retail),
        series=_delta("series", current.series, prior.series),
        total=_delta("total", current.total, prior.total),
    )


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_comparison = prior_period_revenue_split
compare_revenue_split = prior_period_revenue_split
get_prior_period_comparison = prior_period_revenue_split
