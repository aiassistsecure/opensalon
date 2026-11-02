"""Refunds and net revenue for a salon over a date window.

Backend only — no views, templates, or UI. Nothing here is
stored: each figure is computed from the existing services that
own it, which remain the one source of truth.

Definition
----------
For an inclusive window ``[start_date, end_date]``:

* ``gross`` is gross settled revenue — the ``total`` of the
  window's :class:`insights.services.RevenueSplit`, taken
  verbatim from :func:`insights.prior_period._split_for_window`
  (which reuses ``last_7_days_revenue_split`` for 7-day windows
  and the daily trend otherwise). Only completed sales count;
  a sale belongs to the day of its ``completed_at`` when set,
  otherwise its ``created_at``.
* ``refunds`` is the refund total from
  :func:`checkout.refund_report.refund_totals` — ``Refund``
  rows (the append-only record created by
  :func:`checkout.refunds.record_refund`) on completed sales,
  attributed to the day each refund was recorded, judged in
  the salon's timezone. ``refund_count`` is its count.
* ``net`` is ``gross - refunds``, quantised to cents.

Because each figure keeps its owning service's attribution,
a refund recorded inside the window against a sale settled
before it counts in ``refunds`` but not in ``gross`` — so
``net`` can be negative for a window. That is the honest
figure, not an error.

Money is :class:`~decimal.Decimal` throughout, two places.
A reversed window (``end_date`` before ``start_date``) raises
``ValueError``; an empty window yields zeroes, never ``None``.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from checkout.refund_report import refund_totals

from .prior_period import _as_window_date, _split_for_window
from .services import ZERO

__all__ = [
    "RefundsNetRevenue",
    "NetRevenue",
    "refunds_net_revenue",
    "net_revenue",
    "get_refunds_net_revenue",
    "refunds_net",
]

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class RefundsNetRevenue:
    """Gross settled revenue, refunds, and net for one window."""

    gross: Decimal
    refunds: Decimal
    net: Decimal
    refund_count: int
    start_date: date
    end_date: date
    days: int

    @property
    def gross_revenue(self):
        return self.gross

    @property
    def gross_total(self):
        return self.gross

    @property
    def settled_revenue(self):
        return self.gross

    @property
    def refund_total(self):
        return self.refunds

    @property
    def refunds_total(self):
        return self.refunds

    @property
    def net_revenue(self):
        return self.net

    @property
    def net_total(self):
        return self.net

    @property
    def count(self):
        return self.refund_count


#: Alias: the same result under another natural name.
NetRevenue = RefundsNetRevenue


def refunds_net_revenue(salon, start_date=None, end_date=None, **kwargs):
    """Return the :class:`RefundsNetRevenue` for ``salon``.

    ``start_date`` / ``end_date`` are the inclusive window
    (``date``, ``datetime``, or ISO string; ``start`` / ``end``
    and ``since`` / ``until`` are accepted as keyword aliases),
    as in :mod:`insights.prior_period`. See the module
    docstring for the figures' definitions.
    """
    if salon is None:
        raise ValueError("refunds_net_revenue needs a salon")
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
    gross = _split_for_window(salon, start, end).total.quantize(_CENTS)
    totals = refund_totals(salon, start, end)
    refunds = Decimal(totals.total).quantize(_CENTS)
    return RefundsNetRevenue(
        gross=gross,
        refunds=refunds,
        net=(gross - refunds).quantize(_CENTS),
        refund_count=totals.refund_count,
        start_date=start,
        end_date=end,
        days=(end - start).days + 1,
    )


#: Aliases, mirroring the naming convenience in sibling services.
net_revenue = refunds_net_revenue
get_refunds_net_revenue = refunds_net_revenue
refunds_net = refunds_net_revenue
