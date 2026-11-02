"""Tender-mix share service for checkout.

Backend only -- no views, templates, or UI. Read-only.

Answers, for one salon and a date window: what settled takings
were taken by each tender, and what share of the window total
each tender represents.

One source of truth: amounts, the window total, and the payment
count come verbatim from
:func:`checkout.tender_totals.tender_totals` -- only completed
payments count, payments on voided sales are excluded, and every
core ``Payment.Method`` is zero-filled. This module never
re-queries payments; it only derives shares from those totals.

Shares are percentages (x100) of the window total, ``Decimal``
quantized to two places with ``ROUND_HALF_UP``, mirroring
:func:`insights.category_mix._share` and
:mod:`insights.prior_period`: a share is ``None`` when the
window total is zero (no meaningful percentage), while the
amounts and total themselves are ``Decimal('0.00')`` for an
empty window, never ``None`` -- the convention of
:mod:`checkout.summary` and :mod:`checkout.tender_totals`.

A reversed window raises ``ValueError`` (propagated from the
totals service). Core stays provider-agnostic: grouping is by
the core ``Payment.method`` tender slug only.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .tender_totals import tender_totals

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")

__all__ = [
    "TenderMix", "TenderMixEntry", "TenderMixRow",
    "tender_mix", "tender_mix_share", "get_tender_mix",
]


def _share(part, total):
    if not total:
        return None
    return (Decimal(part) * 100 / Decimal(total)).quantize(
        _CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class TenderMixEntry:
    """One tender's total and share of the window total."""

    method: str
    total: Decimal
    share_percent: Decimal | None

    @property
    def amount(self):
        return self.total

    @property
    def tender(self):
        return self.method

    @property
    def share(self):
        return self.share_percent

    share_pct = share


@dataclass(frozen=True)
class TenderMix:
    """A salon's settled takings by tender for one window."""

    salon: object
    start: object
    end: object
    total: Decimal
    count: int
    by_method: dict = field(default_factory=dict)
    shares: dict = field(default_factory=dict)
    entries: list = field(default_factory=list)

    @property
    def salon_id(self):
        return getattr(self.salon, "pk", self.salon)

    @property
    def by_tender(self):
        return self.by_method

    tender_totals = by_tender

    @property
    def share_by_method(self):
        return self.shares

    shares_by_method = share_by_method
    by_share = share_by_method

    @property
    def rows(self):
        return self.entries

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)

    def __getitem__(self, method):
        for entry in self.entries:
            if entry.method == method:
                return entry
        raise KeyError(method)


TenderMixRow = TenderMixEntry


def tender_mix(salon, start=None, end=None, **kwargs):
    """Return the :class:`TenderMix` for ``salon`` over a window.

    ``start`` / ``end`` are datetimes (inclusive range) or dates
    (whole days, inclusive), exactly as in
    :func:`checkout.tender_totals.tender_totals`; the keyword
    aliases ``date_from`` / ``date_to`` and ``since`` / ``until``
    are also accepted. Only that salon's settled takings count.
    A missing salon or a reversed window raises ``ValueError``.
    Read-only: nothing is created, updated, or deleted.
    """
    if salon is None:
        raise ValueError("tender_mix needs a salon")
    if start is None:
        start = kwargs.pop("date_from", kwargs.pop("since", None))
    if end is None:
        end = kwargs.pop("date_to", kwargs.pop("until", None))
    if kwargs:
        raise TypeError(
            f"unexpected arguments: {', '.join(sorted(kwargs))}")
    totals = tender_totals(start, end, salon=salon)
    shares = {
        method: _share(amount, totals.total)
        for method, amount in totals.by_method.items()
    }
    entries = [
        TenderMixEntry(
            method=method, total=amount, share_percent=shares[method])
        for method, amount in totals.by_method.items()
    ]
    return TenderMix(
        salon=salon, start=start, end=end, total=totals.total,
        count=totals.count, by_method=dict(totals.by_method),
        shares=shares, entries=entries,
    )


#: Aliases, mirroring the naming convenience in sibling services.
tender_mix_share = tender_mix
get_tender_mix = tender_mix
