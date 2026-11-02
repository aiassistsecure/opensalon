"""Prior-period comparison for discounts.

Backend only — no views, templates, or UI. Nothing is stored.
Mirrors :mod:`insights.prior_refunds_net`: the prior period is
the equal-length window immediately before the current one,
and each window's figures come verbatim from
:mod:`insights.discounts` — never re-derived here.

``percent_change`` is a :class:`~decimal.Decimal` quantised
to two places, ``None`` when the prior figure is zero (the
``delta`` is always present); a reversed window raises
``ValueError``. Money is :class:`~decimal.Decimal` throughout.

``discount_share_percent`` follows the same rule when both
windows have a share; a window's share is ``None`` when its
gross is zero (see :mod:`insights.discounts`), so the share
comparison is ``None`` when either share is ``None`` — never
faked as zero. Verbatim shares remain on ``current``/``prior``.
"""
from dataclasses import dataclass
from datetime import timedelta

from .discounts import DiscountsReport, discounts_report
from .prior_period import ComponentDelta, _as_window_date, _delta

__all__ = [
    "PriorDiscountsComparison",
    "prior_discounts",
    "prior_period_discounts",
    "compare_discounts",
    "get_prior_discounts",
]


def _share_delta(current, prior):
    if current.discount_share_percent is None \
            or prior.discount_share_percent is None:
        return None
    return _delta("discount_share_percent",
                  current.discount_share_percent,
                  prior.discount_share_percent)


@dataclass(frozen=True)
class PriorDiscountsComparison:
    """Current vs prior :class:`DiscountsReport`, with deltas."""

    current: DiscountsReport
    prior: DiscountsReport
    discount_total: ComponentDelta
    gross: ComponentDelta
    discount_share_percent: ComponentDelta | None

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
            "discount_total": self.discount_total,
            "gross": self.gross,
            "discount_share_percent": self.discount_share_percent,
        }


def prior_discounts(salon, start_date=None, end_date=None, **kwargs):
    """Return the discounts comparison for ``salon``.

    ``start_date`` / ``end_date`` are the inclusive current
    window (``date``, ``datetime``, or ISO string; ``start`` /
    ``end`` and ``since`` / ``until`` are accepted as keyword
    aliases), as in :mod:`insights.prior_period`. See the
    module docstring for the prior-window and zero-prior rules.
    """
    if salon is None:
        raise ValueError("prior_discounts needs a salon")
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
    current = discounts_report(salon, start, end)
    prior = discounts_report(salon, prior_start, prior_end)
    return PriorDiscountsComparison(
        current=current, prior=prior,
        discount_total=_delta(
            "discount_total", current.discount_total,
            prior.discount_total),
        gross=_delta("gross", current.gross, prior.gross),
        discount_share_percent=_share_delta(current, prior),
    )


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_discounts = prior_discounts
compare_discounts = prior_discounts
get_prior_discounts = prior_discounts
