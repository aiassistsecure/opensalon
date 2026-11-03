"""Prior-period tender-totals comparison for checkout.

Backend only, read-only. Combiner-mirror of
:mod:`checkout.prior_tender_mix` built on
:func:`checkout.tender_totals.tender_totals`: amounts, totals
and counts for both windows come verbatim from that service.
Prior period is the immediately preceding equal-length window
(dates: ``[start - length, start - 1 day]``; datetimes shift
back by their duration), as in prior_tender_mix. Per tender:
current/prior, ``delta``, ``percent_change`` (``None`` on zero
prior). Also salon-level ``total``/``count`` MetricDeltas.
Missing/reversed window raises ``ValueError``. Provider-
agnostic: grouping is by the core tender slug only.
"""
import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .tender_totals import tender_totals

_CENTS = Decimal("0.01")

__all__ = ["MetricDelta", "FigureDelta", "PriorTenderTotals",
           "PriorTenderTotalsEntry", "PriorTenderTotalsRow",
           "prior_tender_totals", "prior_period_tender_totals",
           "get_prior_tender_totals", "compare_tender_totals"]


def _pct_change(current, prior):
    if not prior:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior)
            * 100).quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MetricDelta:
    """One figure in both windows, with its change."""

    component: str
    current: object = None
    prior: object = None
    delta: object = None
    percent_change: Decimal | None = None

    @property
    def name(self): return self.component
    @property
    def previous(self): return self.prior
    @property
    def change(self): return self.delta
    @property
    def pct_change(self): return self.percent_change

    def as_dict(self):
        return {"component": self.component, "current": self.current,
                "prior": self.prior, "delta": self.delta,
                "percent_change": self.percent_change}


FigureDelta = MetricDelta


def _count_delta(name, current, prior):
    current, prior = int(current), int(prior)
    return MetricDelta(name, current, prior, current - prior,
                       _pct_change(current, prior))


def _money_delta(name, current, prior):
    current, prior = Decimal(current), Decimal(prior)
    return MetricDelta(name, current, prior,
                       (current - prior).quantize(_CENTS),
                       _pct_change(current, prior))


@dataclass(frozen=True)
class PriorTenderTotalsEntry:
    """One tender in both windows, with its change."""

    method: str
    current: Decimal
    prior: Decimal
    delta: Decimal
    percent_change: Decimal | None

    @property
    def tender(self): return self.method
    @property
    def amount(self): return self.current
    current_amount = amount
    @property
    def prior_amount(self): return self.prior
    @property
    def change(self): return self.delta
    @property
    def pct_change(self): return self.percent_change


@dataclass(frozen=True)
class PriorTenderTotals:
    """Current vs prior tender totals for a window."""

    salon: object
    start: object
    end: object
    prior_start: object
    prior_end: object
    current: object
    prior: object
    entries: list = field(default_factory=list)
    by_method: dict = field(default_factory=dict)
    count: MetricDelta = None
    total: MetricDelta = None

    @property
    def payment_count(self): return self.count
    @property
    def current_count(self):
        return self.count.current if self.count else self.current.count
    @property
    def prior_count(self):
        return self.count.prior if self.count else self.prior.count
    @property
    def salon_id(self): return getattr(self.salon, "pk", self.salon)
    @property
    def current_total(self): return self.current.total
    @property
    def prior_total(self): return self.prior.total
    @property
    def total_delta(self): return self.current.total - self.prior.total
    @property
    def total_percent_change(self):
        return _pct_change(self.current.total, self.prior.total)
    def __iter__(self): return iter(self.entries)
    def __len__(self): return len(self.entries)
    def __getitem__(self, method): return self.by_method[method]


PriorTenderTotalsRow = PriorTenderTotalsEntry


def _prior_window(start, end):
    if isinstance(start, datetime.date) and not isinstance(
            start, datetime.datetime):
        length = (end - start).days + 1
        return (start - datetime.timedelta(days=length),
                start - datetime.timedelta(days=1))
    duration = end - start
    return start - duration, end - duration


def _is_range_bound(value):
    return isinstance(value, (datetime.date, datetime.datetime))


def _resolve(start, end, salon, kwargs):
    # Salon-first form, mirroring prior_tender_mix: (salon, start, end)
    # arrives as start=salon, end=start, salon=end.
    if (start is not None and not _is_range_bound(start)
            and _is_range_bound(end) and _is_range_bound(salon)):
        start, end, salon = end, salon, start
    if salon is None:
        salon = kwargs.pop("salon", None)
    if start is None:
        start = kwargs.pop("date_from", kwargs.pop(
            "since", kwargs.pop("start_date", None)))
    if end is None:
        end = kwargs.pop("date_to", kwargs.pop(
            "until", kwargs.pop("end_date", None)))
    if kwargs:
        raise TypeError(
            f"unexpected arguments: {', '.join(sorted(kwargs))}")
    return start, end, salon


def prior_tender_totals(start=None, end=None, salon=None, **kwargs):
    """Return :class:`PriorTenderTotals` for a window.

    Mirrors :func:`tender_totals` ``(start, end, salon=None)``;
    salon-first ``(salon, start, end)`` also accepted. ``current``
    and ``prior`` are verbatim ``tender_totals`` results.
    """
    start, end, salon = _resolve(start, end, salon, kwargs)
    if start is None or end is None:
        raise ValueError("prior_tender_totals needs both a start and end")
    if end < start:
        raise ValueError("range end must not be before its start")
    current = tender_totals(start, end, salon=salon)
    prior_start, prior_end = _prior_window(start, end)
    prior = tender_totals(prior_start, prior_end, salon=salon)
    entries = []
    for method, amount in current.by_method.items():
        p = prior.by_method[method]
        entries.append(PriorTenderTotalsEntry(
            method=method, current=amount, prior=p,
            delta=(amount - p).quantize(_CENTS),
            percent_change=_pct_change(amount, p)))
    return PriorTenderTotals(
        salon=salon, start=start, end=end, prior_start=prior_start,
        prior_end=prior_end, current=current, prior=prior,
        entries=entries, by_method={e.method: e for e in entries},
        count=_count_delta("count", current.count, prior.count),
        total=_money_delta("total", current.total, prior.total))


#: Aliases, mirroring sibling services.
prior_period_tender_totals = prior_tender_totals
get_prior_tender_totals = prior_tender_totals
compare_tender_totals = prior_tender_totals
