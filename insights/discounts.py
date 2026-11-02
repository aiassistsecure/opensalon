"""Discounts for a salon over a date window.

Backend only — no views, templates, or UI. Nothing here is
stored: each figure is computed from the rows that own it.

Definition
----------
For an inclusive window ``[start_date, end_date]``:
``discount_total`` is every recorded discount on completed
sales in the window — each sale's ``Sale.discount_amount``
plus every line's ``SaleItem.discount_amount`` (exactly
:attr:`checkout.models.Sale.discount_total`, summed). Only
completed sales count; a sale belongs to the day of its
``completed_at`` when set, otherwise its ``created_at``,
judged in the salon's timezone — the attribution established
in :mod:`insights.services`. ``gross`` is the ``total`` of
the window's :class:`insights.services.RevenueSplit`, taken
verbatim from :func:`insights.prior_period._split_for_window`
(never re-derived here). ``discount_share_percent`` is
``discount_total / gross * 100``, a Decimal quantised to two
places, or ``None`` when ``gross`` is zero, mirroring
:mod:`insights.prior_period`. Money is Decimal throughout;
a reversed window raises ``ValueError``; an empty window
yields zeroes and a ``None`` share.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q, Sum

from checkout.models import Sale, SaleItem

from .prior_period import _as_window_date, _split_for_window
from .services import ZERO, _salon_tz

__all__ = [
    "DiscountsReport",
    "DiscountReport",
    "discounts_report",
    "discount_report",
    "get_discounts_report",
    "discounts",
]

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class DiscountsReport:
    """Gross revenue, recorded discounts, and their share."""

    discount_total: Decimal
    gross: Decimal
    discount_share_percent: Decimal | None
    start_date: date
    end_date: date
    days: int

    @property
    def discounts(self):
        return self.discount_total

    discount = discounts
    discounts_total = discounts

    @property
    def gross_revenue(self):
        return self.gross

    gross_total = gross_revenue

    @property
    def discount_share(self):
        return self.discount_share_percent

    share_percent = discount_share
    share = discount_share


#: Alias: the same result under another natural name.
DiscountReport = DiscountsReport


def discounts_report(salon, start_date=None, end_date=None, **kwargs):
    """Return the :class:`DiscountsReport` for ``salon``.

    ``start_date`` / ``end_date`` are the inclusive window
    (``date``, ``datetime``, or ISO string; ``start`` / ``end``
    and ``since`` / ``until`` are keyword aliases), as in
    :mod:`insights.prior_period`. See the module docstring.
    """
    if salon is None:
        raise ValueError("discounts_report needs a salon")
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
    tz = _salon_tz(salon)
    start_dt = datetime.combine(start, time.min, tzinfo=tz)
    end_dt = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)
    sales = Sale.objects.filter(
        salon=salon, status=Sale.Status.COMPLETED,
    ).filter(
        Q(completed_at__gte=start_dt, completed_at__lt=end_dt)
        | Q(completed_at__isnull=True,
            created_at__gte=start_dt, created_at__lt=end_dt)
    )
    sale_discount = sales.aggregate(amount=Sum("discount_amount"))["amount"]
    item_discount = SaleItem.objects.filter(sale__in=sales).aggregate(
        amount=Sum("discount_amount"))["amount"]
    discount_total = (
        (Decimal(sale_discount) if sale_discount is not None else ZERO)
        + (Decimal(item_discount) if item_discount is not None else ZERO)
    ).quantize(_CENTS)
    if gross == ZERO:
        share = None
    else:
        share = (discount_total / gross * 100).quantize(
            _CENTS, rounding=ROUND_HALF_UP)
    return DiscountsReport(
        discount_total=discount_total,
        gross=gross,
        discount_share_percent=share,
        start_date=start,
        end_date=end,
        days=(end - start).days + 1,
    )


#: Aliases, mirroring the naming convenience in sibling services.
discount_report = discounts_report
get_discounts_report = discounts_report
discounts = discounts_report
