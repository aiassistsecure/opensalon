"""Prior-period cashup-history comparison for checkout.

Backend only, read-only. Built ON TOP of
:mod:`checkout.cashup_history` — the range summaries for both
windows are that service's verbatim (``cashup_count``,
``total_taken``, by-tender totals, ``expected_total`` and
``variance``); nothing is recomputed here. The prior period is
the immediately preceding equal-length window: for date windows
of ``length = (end - start).days + 1`` days, ``[start - length,
start - 1 day]``; datetime windows shift back by their duration.
Each figure carries ``current``, ``prior``, ``delta`` and
``percent_change`` (Decimal, two places, ROUND_HALF_UP),
``None`` when the prior figure is zero. ``expected_total`` /
``variance`` stay ``None`` (unknown) when a window's cashups
carry no expected figures — never a fabricated zero — and their
delta is then ``None`` too. The by-tender comparison is the
union of both windows' tender keys, zero-filled on the missing
side. A reversed/missing window (or salon) raises ``ValueError``.
A cashup is a snapshot, never a lock. Provider-agnostic core.
"""
import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .cashup_history import cashup_history

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")
__all__ = ["MetricDelta", "FigureDelta", "PriorCashupHistory",
           "PriorCashupHistoryComparison", "PriorCashupTenderEntry",
           "prior_cashup_history", "prior_period_cashup_history",
           "get_prior_cashup_history", "compare_cashup_history"]


def _pct_change(current, prior):
    if current is None or prior is None or not Decimal(prior):
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior)
            * 100).quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MetricDelta:
    """One figure in both periods, with its change."""

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


def _money_delta(name, current, prior):
    if current is None or prior is None:
        return MetricDelta(name, current, prior, None, None)
    current, prior = Decimal(current), Decimal(prior)
    return MetricDelta(name, current, prior,
                       (current - prior).quantize(_CENTS, rounding=ROUND_HALF_UP),
                       _pct_change(current, prior))


def _count_delta(name, current, prior):
    current, prior = int(current), int(prior)
    return MetricDelta(name, current, prior, current - prior,
                       _pct_change(current, prior))


@dataclass(frozen=True)
class PriorCashupTenderEntry:
    """One tender's range total in both windows, with its change."""

    method: str
    current: Decimal
    prior: Decimal
    delta: Decimal
    percent_change: Decimal | None

    @property
    def tender(self): return self.method
    @property
    def current_amount(self): return self.current
    @property
    def prior_amount(self): return self.prior
    @property
    def change(self): return self.delta
    @property
    def pct_change(self): return self.percent_change
    @property
    def metric(self):
        return MetricDelta(f"tender_{self.method}", self.current,
                           self.prior, self.delta, self.percent_change)


@dataclass(frozen=True)
class PriorCashupHistory:
    """Current vs prior cashup-history range summaries."""

    salon: object
    start: object
    end: object
    prior_start: object
    prior_end: object
    current: object
    prior: object
    cashup_count: MetricDelta = None
    total_taken: MetricDelta = None
    expected_total: MetricDelta = None
    variance: MetricDelta = None
    by_tender: dict = field(default_factory=dict)
    entries: list = field(default_factory=list)

    @property
    def salon_id(self): return getattr(self.salon, "pk", self.salon)
    @property
    def date_from(self): return self.start
    @property
    def date_to(self): return self.end
    @property
    def current_summary(self): return self.current.summary
    @property
    def prior_summary(self): return self.prior.summary
    @property
    def tender_entries(self): return self.entries
    @property
    def is_locked(self): return False

    def __iter__(self): return iter(self.entries)
    def __len__(self): return len(self.entries)
    def __getitem__(self, method): return self.by_tender[method]


PriorCashupHistoryComparison = PriorCashupHistory


def _prior_window(start, end):
    if isinstance(start, datetime.date) and not isinstance(
            start, datetime.datetime):
        length = (end - start).days + 1
        return (start - datetime.timedelta(days=length),
                start - datetime.timedelta(days=1))
    duration = end - start
    return start - duration, end - duration


def prior_cashup_history(salon, start=None, end=None, **kwargs):
    """Return the :class:`PriorCashupHistory` for ``salon``.

    ``start`` / ``end`` mirror :mod:`checkout.cashup_history`
    (aliases ``date_from``/``date_to``/``start_date``/``end_date``
    accepted). Missing salon/bound or a reversed window raises
    ``ValueError``.
    """
    if salon is None:
        raise ValueError("prior_cashup_history needs a salon")
    if start is None:
        start = kwargs.pop("date_from", kwargs.pop(
            "since", kwargs.pop("start_date", None)))
    if end is None:
        end = kwargs.pop("date_to", kwargs.pop(
            "until", kwargs.pop("end_date", None)))
    if kwargs:
        raise TypeError(f"unexpected arguments: {', '.join(sorted(kwargs))}")
    if start is None or end is None:
        raise ValueError("prior_cashup_history needs both a start and end")
    if end < start:
        raise ValueError("range end must not be before its start")
    current = cashup_history(salon, start, end)
    prior_start, prior_end = _prior_window(start, end)
    prior = cashup_history(salon, prior_start, prior_end)
    cur_sum, pri_sum = current.summary, prior.summary
    slugs = list(cur_sum.by_tender) + [
        slug for slug in pri_sum.by_tender if slug not in cur_sum.by_tender]
    entries = []
    for slug in slugs:
        d = _money_delta(f"tender_{slug}", cur_sum.by_tender.get(slug, _ZERO),
                         pri_sum.by_tender.get(slug, _ZERO))
        entries.append(PriorCashupTenderEntry(
            method=slug, current=d.current, prior=d.prior,
            delta=d.delta, percent_change=d.percent_change))
    return PriorCashupHistory(
        salon=salon, start=start, end=end, prior_start=prior_start,
        prior_end=prior_end, current=current, prior=prior,
        cashup_count=_count_delta("cashup_count", cur_sum.cashup_count,
                                  pri_sum.cashup_count),
        total_taken=_money_delta("total_taken", cur_sum.total_taken,
                                 pri_sum.total_taken),
        expected_total=_money_delta("expected_total", cur_sum.expected_total,
                                    pri_sum.expected_total),
        variance=_money_delta("variance", cur_sum.variance, pri_sum.variance),
        by_tender={e.method: e.metric for e in entries}, entries=entries)


#: Aliases, mirroring sibling services.
prior_period_cashup_history = prior_cashup_history
get_prior_cashup_history = prior_cashup_history
compare_cashup_history = prior_cashup_history
