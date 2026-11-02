"""Prior-period comparison for refunds and net revenue.

Backend only — no views, templates, or UI. Nothing is stored.
Mirrors :mod:`insights.prior_period`: the prior period is the
equal-length window immediately before the current one, and
each window's figures come verbatim from
:mod:`insights.refunds_net` — never re-derived here.

``percent_change`` is a :class:`~decimal.Decimal` quantised
to two places, ``None`` when the prior figure is zero (the
``delta`` is always present); a reversed window raises
``ValueError``. Money is :class:`~decimal.Decimal` throughout.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .prior_period import ComponentDelta, _as_window_date, _delta
from .refunds_net import RefundsNetRevenue, refunds_net_revenue

__all__ = [
    "PriorRefundsNetComparison",
    "prior_refunds_net",
    "prior_period_refunds_net",
    "compare_refunds_net",
    "get_prior_refunds_net",
]


@dataclass(frozen=True)
class PriorRefundsNetComparison:
    """Current vs prior :class:`RefundsNetRevenue`, with deltas."""

    current: RefundsNetRevenue
    prior: RefundsNetRevenue
    gross: ComponentDelta
    refunds: ComponentDelta
    net: ComponentDelta
    refund_count: ComponentDelta

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
            "gross": self.gross, "refunds": self.refunds,
            "net": self.net, "refund_count": self.refund_count,
        }


def prior_refunds_net(salon, start_date=None, end_date=None, **kwargs):
    """Return the refunds/net comparison for ``salon``.

    ``start_date`` / ``end_date`` are the inclusive current
    window (``date``, ``datetime``, or ISO string; ``start`` /
    ``end`` and ``since`` / ``until`` are accepted as keyword
    aliases), as in :mod:`insights.prior_period`. See the
    module docstring for the prior-window and zero-prior rules.
    """
    if salon is None:
        raise ValueError("prior_refunds_net needs a salon")
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
    current = refunds_net_revenue(salon, start, end)
    prior = refunds_net_revenue(salon, prior_start, prior_end)
    return PriorRefundsNetComparison(
        current=current, prior=prior,
        gross=_delta("gross", current.gross, prior.gross),
        refunds=_delta("refunds", current.refunds, prior.refunds),
        net=_delta("net", current.net, prior.net),
        refund_count=_delta(
            "refund_count",
            Decimal(current.refund_count), Decimal(prior.refund_count)),
    )


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_refunds_net = prior_refunds_net
compare_refunds_net = prior_refunds_net
get_prior_refunds_net = prior_refunds_net
