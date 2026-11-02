"""Prior-period tender-mix comparison for checkout.

Backend only, read-only. The prior period is the immediately
preceding equal-length window: for date windows of
``length = (end - start).days + 1`` days, ``[start - length,
start - 1 day]``; datetime windows shift back by their duration.
Amounts/shares come verbatim from :mod:`checkout.tender_mix`
(one source of truth). Per tender: current/prior amounts and
shares, ``delta``, ``percent_change`` (two places). Share is
``None`` on a zero window total; ``percent_change`` is ``None``
on a zero prior amount. Reversed window raises ``ValueError``.
Salon level only, the result also carries ``count``: a
MetricDelta-shaped payment-count delta whose current/prior
values are ``TenderMix.count`` verbatim for both windows (no
new counting path); per-method entries gain nothing, as the
source carries no per-method count.
"""
import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .tender_mix import tender_mix

_CENTS = Decimal("0.01")

__all__ = [
    "MetricDelta", "FigureDelta",
    "PriorTenderMix", "PriorTenderMixEntry", "PriorTenderMixRow",
    "prior_tender_mix", "prior_period_tender_mix",
    "get_prior_tender_mix", "compare_tender_mix"]


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
    def name(self):
        return self.component

    @property
    def previous(self):
        return self.prior

    @property
    def change(self):
        return self.delta

    @property
    def pct_change(self):
        return self.percent_change

    def as_dict(self):
        return {"component": self.component, "current": self.current,
                "prior": self.prior, "delta": self.delta,
                "percent_change": self.percent_change}


FigureDelta = MetricDelta


def _count_delta(name, current, prior):
    current, prior = int(current), int(prior)
    return MetricDelta(name, current, prior, current - prior,
                       _pct_change(current, prior))


@dataclass(frozen=True)
class PriorTenderMixEntry:
    """One tender in both windows, with its change."""

    method: str
    current: Decimal
    prior: Decimal
    delta: Decimal
    percent_change: Decimal | None
    current_share_percent: Decimal | None
    prior_share_percent: Decimal | None

    @property
    def tender(self):
        return self.method

    @property
    def amount(self):
        return self.current

    current_amount = amount

    @property
    def prior_amount(self):
        return self.prior

    @property
    def change(self):
        return self.delta

    @property
    def pct_change(self):
        return self.percent_change

    @property
    def current_share(self):
        return self.current_share_percent

    @property
    def prior_share(self):
        return self.prior_share_percent


@dataclass(frozen=True)
class PriorTenderMix:
    """Current vs prior tender mix for one salon."""

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

    @property
    def payment_count(self):
        return self.count

    @property
    def current_count(self):
        return self.count.current if self.count else self.current.count

    @property
    def prior_count(self):
        return self.count.prior if self.count else self.prior.count

    @property
    def salon_id(self):
        return getattr(self.salon, "pk", self.salon)

    @property
    def current_total(self):
        return self.current.total

    @property
    def prior_total(self):
        return self.prior.total

    @property
    def total_delta(self):
        return self.current.total - self.prior.total

    @property
    def total_percent_change(self):
        return _pct_change(self.current.total, self.prior.total)

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, method):
        return self.by_method[method]


PriorTenderMixRow = PriorTenderMixEntry


def _prior_window(start, end):
    if isinstance(start, datetime.date) and not isinstance(
            start, datetime.datetime):
        length = (end - start).days + 1
        return (start - datetime.timedelta(days=length),
                start - datetime.timedelta(days=1))
    duration = end - start
    return start - duration, end - duration


def prior_tender_mix(salon, start=None, end=None, **kwargs):
    """Return the :class:`PriorTenderMix` for ``salon``.

    ``start`` / ``end`` mirror :mod:`checkout.tender_mix` (aliases
    ``date_from``/``since``/``start_date`` etc. accepted). Missing
    salon/bound or reversed window raises ``ValueError``.
    """
    if salon is None:
        raise ValueError("prior_tender_mix needs a salon")
    if start is None:
        start = kwargs.pop("date_from", kwargs.pop(
            "since", kwargs.pop("start_date", None)))
    if end is None:
        end = kwargs.pop("date_to", kwargs.pop(
            "until", kwargs.pop("end_date", None)))
    if kwargs:
        raise TypeError(
            f"unexpected arguments: {', '.join(sorted(kwargs))}")
    if start is None or end is None:
        raise ValueError("prior_tender_mix needs both a start and end")
    if end < start:
        raise ValueError("range end must not be before its start")
    current = tender_mix(salon, start, end)
    prior_start, prior_end = _prior_window(start, end)
    prior = tender_mix(salon, prior_start, prior_end)
    entries = []
    for entry in current.entries:
        p = prior[entry.method]
        entries.append(PriorTenderMixEntry(
            method=entry.method, current=entry.total, prior=p.total,
            delta=entry.total - p.total,
            percent_change=_pct_change(entry.total, p.total),
            current_share_percent=entry.share_percent,
            prior_share_percent=p.share_percent))
    return PriorTenderMix(
        salon=salon, start=start, end=end, prior_start=prior_start,
        prior_end=prior_end, current=current, prior=prior,
        entries=entries, by_method={e.method: e for e in entries},
        count=_count_delta("count", current.count, prior.count))


#: Aliases, mirroring sibling services.
prior_period_tender_mix = prior_tender_mix
get_prior_tender_mix = prior_tender_mix
compare_tender_mix = prior_tender_mix
