"""Prior-period comparison for retention + returning clients.

Backend only — no views, templates, or UI. Nothing is stored.
Mirrors :mod:`insights.prior_popularity_client_value`: prior
is the equal-length window immediately before the current
one; figures come verbatim from :mod:`insights.retention`
and :mod:`insights.returning`, never re-derived;
``percent_change`` is a Decimal quantised to two places,
``None`` when prior is zero (``delta`` always present);
reversed window raises ``ValueError``. Retention floats
convert via ``Decimal(str(value))`` (no float noise).
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .prior_period import ComponentDelta, _as_window_date, _delta
from .retention import repeat_visit_retention
from .returning import new_vs_returning_revenue

__all__ = [
    "RetentionPriorComparison", "ReturningPriorComparison",
    "prior_period_retention", "prior_period_returning",
    "prior_period_returning_revenue", "compare_retention",
    "compare_returning",
]


def _count_delta(component, current, prior):
    return _delta(component, Decimal(current), Decimal(prior))


def _float_delta(component, current, prior):
    return _delta(component, Decimal(str(current)), Decimal(str(prior)))


class _Base:
    """Shared window-bound properties for both comparisons."""

    @property
    def previous(self): return self.prior
    @property
    def start_date(self): return self.current.start_date
    @property
    def end_date(self): return self.current.end_date
    @property
    def prior_start_date(self): return self.prior.start_date
    @property
    def prior_end_date(self): return self.prior.end_date
    @property
    def days(self): return (self.end_date - self.start_date).days + 1


@dataclass(frozen=True)
class RetentionPriorComparison(_Base):
    """Current vs prior :class:`Retention`, with deltas."""

    current: object
    prior: object
    active_clients: ComponentDelta
    repeat_clients: ComponentDelta
    total_visits: ComponentDelta
    repeat_rate: ComponentDelta
    average_visits_per_active_client: ComponentDelta


@dataclass(frozen=True)
class ReturningPriorComparison(_Base):
    """Current vs prior :class:`ReturningRevenue`, with deltas."""

    current: object
    prior: object
    returning_revenue: ComponentDelta
    new_revenue: ComponentDelta
    unattributed_revenue: ComponentDelta
    total: ComponentDelta
    returning_sale_count: ComponentDelta
    new_sale_count: ComponentDelta
    unattributed_sale_count: ComponentDelta
    total_sale_count: ComponentDelta


def _window(salon, start_date, end_date, kwargs):
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
    return start, end, start - timedelta(days=length), \
        start - timedelta(days=1)


def prior_period_retention(salon, start_date=None, end_date=None, **kwargs):
    """Return retention for the current vs prior period."""
    start, end, p_start, p_end = _window(salon, start_date, end_date, kwargs)
    current = repeat_visit_retention(salon, start, end)
    prior = repeat_visit_retention(salon, p_start, p_end)
    return RetentionPriorComparison(
        current=current, prior=prior,
        active_clients=_count_delta("active_clients", current.active_clients, prior.active_clients),
        repeat_clients=_count_delta("repeat_clients", current.repeat_clients, prior.repeat_clients),
        total_visits=_count_delta("total_visits", current.total_visits, prior.total_visits),
        repeat_rate=_float_delta("repeat_rate", current.repeat_rate, prior.repeat_rate),
        average_visits_per_active_client=_float_delta(
            "average_visits_per_active_client",
            current.average_visits_per_active_client,
            prior.average_visits_per_active_client),
    )


def prior_period_returning_revenue(salon, start_date=None, end_date=None, **kwargs):
    """Return new-vs-returning revenue for current vs prior."""
    start, end, p_start, p_end = _window(salon, start_date, end_date, kwargs)
    current = new_vs_returning_revenue(salon, start, end)
    prior = new_vs_returning_revenue(salon, p_start, p_end)
    return ReturningPriorComparison(
        current=current, prior=prior,
        returning_revenue=_delta("returning_revenue", current.returning_revenue, prior.returning_revenue),
        new_revenue=_delta("new_revenue", current.new_revenue, prior.new_revenue),
        unattributed_revenue=_delta("unattributed_revenue", current.unattributed_revenue, prior.unattributed_revenue),
        total=_delta("total", current.total, prior.total),
        returning_sale_count=_count_delta("returning_sale_count", current.returning_sale_count, prior.returning_sale_count),
        new_sale_count=_count_delta("new_sale_count", current.new_sale_count, prior.new_sale_count),
        unattributed_sale_count=_count_delta("unattributed_sale_count", current.unattributed_sale_count, prior.unattributed_sale_count),
        total_sale_count=_count_delta("total_sale_count", current.total_sale_count, prior.total_sale_count),
    )


prior_period_returning = prior_period_returning_revenue
compare_retention = prior_period_retention
compare_returning = prior_period_returning_revenue
