"""Prior-period comparison for the checkout refund report.

Backend only, read-only. Built ON TOP of :mod:`checkout.refund_report`
— all figures for both windows are ``refund_totals`` verbatim (called
twice); nothing is recomputed here. Distinct from
:mod:`insights.prior_refunds_net` (headline figure only): this prior
compares the per-tender and per-day breakdowns. Prior = immediately
preceding equal-length window. By-day rows pair offset-aligned days,
and each paired day also carries ``by_tender`` amount deltas and
``counts_by_tender`` count deltas for that day pair, taken verbatim
from ``refund_report``'s own per-day ``RefundsByDay`` dicts for both
windows. Each figure: current/prior/delta/percent_change (Decimal, 2dp,
ROUND_HALF_UP), None when prior is zero. By-tender = union of both
windows' keys, zero-filled. Missing salon or reversed/missing window
raises ValueError. Provider-agnostic: core tender slugs only.
"""
import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .refund_report import refund_totals

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")
__all__ = ["MetricDelta", "FigureDelta", "PriorRefundReport",
           "PriorRefundReportComparison", "PriorRefundTenderEntry",
           "PriorRefundDayEntry", "prior_refund_report",
           "prior_period_refund_report", "get_prior_refund_report",
           "compare_refund_report"]
FIGURES = ("refund_count", "total")


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
class PriorRefundTenderEntry:
    """One tender's refund amount + count in both windows."""
    tender: str
    total: MetricDelta = None
    refund_count: MetricDelta = None
    @property
    def method(self): return self.tender
    def __getitem__(self, figure): return getattr(self, figure)


@dataclass(frozen=True)
class PriorRefundDayEntry:
    """One current day paired with its prior-window counterpart.

    ``by_tender`` maps tender slug to that day pair's refund-amount
    delta and ``counts_by_tender`` to its refund-count delta, both
    verbatim from the two days' ``RefundsByDay`` dicts (union of
    tender slugs, zero-filled).
    """
    day: object = None
    prior_day: object = None
    refund_count: MetricDelta = None
    total: MetricDelta = None
    by_tender: dict = field(default_factory=dict)
    counts_by_tender: dict = field(default_factory=dict)
    @property
    def date(self): return self.day
    @property
    def prior_date(self): return self.prior_day
    def __getitem__(self, tender): return self.by_tender[tender]


@dataclass(frozen=True)
class PriorRefundReport:
    """Current vs prior refund report for one salon."""
    salon: object
    start: object
    end: object
    prior_start: object
    prior_end: object
    current: object
    prior: object
    refund_count: MetricDelta = None
    total: MetricDelta = None
    by_tender: dict = field(default_factory=dict)
    entries: list = field(default_factory=list)
    by_day: dict = field(default_factory=dict)
    day_entries: list = field(default_factory=list)
    @property
    def salon_id(self): return getattr(self.salon, "pk", self.salon)
    @property
    def date_from(self): return self.start
    @property
    def date_to(self): return self.end
    @property
    def tender_entries(self): return self.entries
    @property
    def days(self): return self.day_entries
    def __iter__(self): return iter(self.entries)
    def __len__(self): return len(self.entries)
    def __getitem__(self, tender): return self.by_tender[tender]


PriorRefundReportComparison = PriorRefundReport


def prior_refund_report(salon, start=None, end=None, **kwargs):
    """Return the :class:`PriorRefundReport` for ``salon``.

    ``start`` / ``end`` mirror :mod:`checkout.refund_report`
    (aliases ``date_from``/``date_to``/``start_date``/``end_date``
    accepted). Missing salon/bound or reversed window raises
    ``ValueError``.
    """
    if salon is None:
        raise ValueError("prior_refund_report needs a salon")
    if start is None:
        start = kwargs.pop("date_from", kwargs.pop(
            "since", kwargs.pop("start_date", None)))
    if end is None:
        end = kwargs.pop("date_to", kwargs.pop(
            "until", kwargs.pop("end_date", None)))
    if kwargs:
        raise TypeError(f"unexpected arguments: {', '.join(sorted(kwargs))}")
    if start is None or end is None:
        raise ValueError("prior_refund_report needs both a start and end")
    if isinstance(start, datetime.date) and isinstance(end, datetime.date) \
            and end < start:
        raise ValueError("range end must not be before its start")
    current = refund_totals(salon, start, end)
    length = (current.date_to - current.date_from).days + 1
    prior_end = current.date_from - datetime.timedelta(days=1)
    prior_start = prior_end - datetime.timedelta(days=length - 1)
    prior = refund_totals(salon, prior_start, prior_end)
    slugs = list(current.by_tender) + [
        s for s in prior.by_tender if s not in current.by_tender]
    entries = [PriorRefundTenderEntry(
        tender=s,
        total=_money_delta("total", current.by_tender.get(s, _ZERO),
                           prior.by_tender.get(s, _ZERO)),
        refund_count=_count_delta(
            "refund_count", current.counts_by_tender.get(s, 0),
            prior.counts_by_tender.get(s, 0))) for s in slugs]
    def _day_entry(cur, pri):
        slugs = list(cur.by_tender) + [
            s for s in pri.by_tender if s not in cur.by_tender]
        return PriorRefundDayEntry(
            day=cur.day, prior_day=pri.day,
            refund_count=_count_delta("refund_count", cur.refund_count,
                                      pri.refund_count),
            total=_money_delta("total", cur.total, pri.total),
            by_tender={s: _money_delta(
                "total", cur.by_tender.get(s, _ZERO),
                pri.by_tender.get(s, _ZERO)) for s in slugs},
            counts_by_tender={s: _count_delta(
                "refund_count", cur.counts_by_tender.get(s, 0),
                pri.counts_by_tender.get(s, 0)) for s in slugs})

    day_entries = [_day_entry(cur, pri)
                   for cur, pri in zip(current.days, prior.days)]
    return PriorRefundReport(
        salon=salon, start=current.date_from, end=current.date_to,
        prior_start=prior.date_from, prior_end=prior.date_to,
        current=current, prior=prior,
        refund_count=_count_delta("refund_count", current.refund_count,
                                  prior.refund_count),
        total=_money_delta("total", current.total, prior.total),
        by_tender={e.tender: e for e in entries}, entries=entries,
        by_day={e.day: e for e in day_entries}, day_entries=day_entries)


#: Aliases, mirroring sibling services.
prior_period_refund_report = prior_refund_report
get_prior_refund_report = prior_refund_report
compare_refund_report = prior_refund_report
