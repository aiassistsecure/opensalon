"""Prior-period cashup-detail comparison for checkout.

Backend only, read-only. Built ON TOP of :mod:`checkout.cashup_detail`
— per-tender gross / refunds / voids / net and payment / refund /
void counts for both windows are that service's verbatim; nothing is
recomputed, re-queried, or recounted here (top-level counts are sums
of the source's own per-tender counts). Distinct from
:mod:`checkout.prior_cashup_history` (stored ``Cashup`` snapshots):
this source recomputes from ``Payment`` + ``Refund`` rows, so the two
priors stay one-truth each. Prior = immediately preceding equal-length
window ``[start - length, start - 1 day]``, derived from the current
detail's normalised bounds. Each figure: ``current``, ``prior``,
``delta``, ``percent_change`` (Decimal, 2dp, ROUND_HALF_UP), ``None``
when prior is zero. By-tender = union of both windows' keys,
zero-filled on the missing side. Reversed/missing window or salon
raises ``ValueError``. Provider-agnostic: core tender slugs only.
"""
import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .cashup_detail import cashup_detail

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")
__all__ = ["MetricDelta", "FigureDelta", "PriorCashupDetail",
           "PriorCashupDetailComparison", "PriorCashupDetailTenderEntry",
           "prior_cashup_detail", "prior_period_cashup_detail",
           "get_prior_cashup_detail", "compare_cashup_detail"]
FIGURES = ("gross", "refunds", "voids", "net")
COUNT_FIGURES = ("payment_count", "refund_count", "void_count")
ALL_FIGURES = FIGURES + COUNT_FIGURES


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
    current, prior = Decimal(current), Decimal(prior)
    return MetricDelta(name, current, prior,
                       (current - prior).quantize(_CENTS, rounding=ROUND_HALF_UP),
                       _pct_change(current, prior))


def _count_delta(name, current, prior):
    current, prior = int(current), int(prior)
    return MetricDelta(name, current, prior, current - prior,
                       _pct_change(current, prior))


@dataclass(frozen=True)
class PriorCashupDetailTenderEntry:
    """One tender's detail figures in both windows, with changes."""
    tender: str
    gross: MetricDelta = None
    refunds: MetricDelta = None
    voids: MetricDelta = None
    net: MetricDelta = None
    payment_count: MetricDelta = None
    refund_count: MetricDelta = None
    void_count: MetricDelta = None
    @property
    def method(self): return self.tender
    def __getitem__(self, figure): return getattr(self, figure)


@dataclass(frozen=True)
class PriorCashupDetail:
    """Current vs prior cashup detail for one salon."""
    salon: object
    start: object
    end: object
    prior_start: object
    prior_end: object
    current: object
    prior: object
    gross: MetricDelta = None
    refunds: MetricDelta = None
    voids: MetricDelta = None
    net: MetricDelta = None
    payment_count: MetricDelta = None
    refund_count: MetricDelta = None
    void_count: MetricDelta = None
    by_tender: dict = field(default_factory=dict)
    entries: list = field(default_factory=list)
    @property
    def salon_id(self): return getattr(self.salon, "pk", self.salon)
    @property
    def date_from(self): return self.start
    @property
    def date_to(self): return self.end
    @property
    def current_detail(self): return self.current
    @property
    def prior_detail(self): return self.prior
    @property
    def tender_entries(self): return self.entries
    def __iter__(self): return iter(self.entries)
    def __len__(self): return len(self.entries)
    def __getitem__(self, tender): return self.by_tender[tender]


PriorCashupDetailComparison = PriorCashupDetail


def _tender_entry(tender, cur, pri):
    return PriorCashupDetailTenderEntry(
        tender=tender,
        **{n: _money_delta(n, getattr(cur, n, _ZERO), getattr(pri, n, _ZERO))
           for n in FIGURES},
        **{n: _count_delta(n, getattr(cur, n, 0), getattr(pri, n, 0))
           for n in COUNT_FIGURES})


def prior_cashup_detail(salon, start=None, end=None, **kwargs):
    """Return the :class:`PriorCashupDetail` for ``salon``.

    ``start`` / ``end`` mirror :mod:`checkout.cashup_detail` (aliases
    ``date_from``/``date_to``/``start_date``/``end_date`` accepted).
    Missing salon/bound or reversed window raises ``ValueError``.
    """
    if salon is None:
        raise ValueError("prior_cashup_detail needs a salon")
    if start is None:
        start = kwargs.pop("date_from", kwargs.pop(
            "since", kwargs.pop("start_date", None)))
    if end is None:
        end = kwargs.pop("date_to", kwargs.pop(
            "until", kwargs.pop("end_date", None)))
    if kwargs:
        raise TypeError(f"unexpected arguments: {', '.join(sorted(kwargs))}")
    if start is None or end is None:
        raise ValueError("prior_cashup_detail needs both a start and end")
    if isinstance(start, datetime.date) and isinstance(end, datetime.date) \
            and end < start:
        raise ValueError("range end must not be before its start")
    current = cashup_detail(salon, start, end)
    length = (current.date_to - current.date_from).days + 1
    prior_end = current.date_from - datetime.timedelta(days=1)
    prior_start = prior_end - datetime.timedelta(days=length - 1)
    prior = cashup_detail(salon, prior_start, prior_end)
    slugs = list(current.by_tender) + [
        s for s in prior.by_tender if s not in current.by_tender]
    entries = [_tender_entry(s, current.by_tender.get(s),
                             prior.by_tender.get(s)) for s in slugs]
    totals = {n: _money_delta(n, getattr(current, n), getattr(prior, n))
              for n in FIGURES}
    totals.update({n: _count_delta(
        n, sum(getattr(d, n) for d in current.by_tender.values()),
        sum(getattr(d, n) for d in prior.by_tender.values()))
        for n in COUNT_FIGURES})
    return PriorCashupDetail(
        salon=salon, start=current.date_from, end=current.date_to,
        prior_start=prior.date_from, prior_end=prior.date_to,
        current=current, prior=prior, **totals,
        by_tender={e.tender: e for e in entries}, entries=entries)


#: Aliases, mirroring sibling services.
prior_period_cashup_detail = prior_cashup_detail
get_prior_cashup_detail = prior_cashup_detail
compare_cashup_detail = prior_cashup_detail
