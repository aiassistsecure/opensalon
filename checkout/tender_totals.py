"""Read-only tender-totals service for checkout.

Complements :mod:`checkout.cashup`: a cashup stores an immutable
close-out snapshot for one salon, while this service answers the
same underlying question on demand — for any date range, optionally
scoped to one salon — and records nothing.

Only completed payments count toward totals: pending and failed
payments moved no money, refunded payments are excluded (their
original completed payment is what was taken), and payments on
voided sales are excluded. That follows the ``Payment`` model's
own status conventions in :mod:`checkout.models`.

Core stays provider-agnostic: grouping is by the core
``Payment.method`` tender slug only, with no provider-specific
field or assumption anywhere here.
"""
import datetime
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from .models import Payment, Sale

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class TenderTotals:
    """Totals for a period: per-method sums, grand total, count."""

    by_method: dict
    total: Decimal
    count: int
    start: object = None
    end: object = None

    def __getitem__(self, method):
        return self.by_method[method]

    def items(self):
        return self.by_method.items()


def _as_bounds(start, end):
    """Normalise ``start``/``end`` to (gte, lte-or-lt, is_date_range).

    Plain ``date`` values mean whole days, inclusive at both ends;
    datetimes are taken as an inclusive instant range, matching
    :func:`checkout.cashup.compute_tender_totals`.
    """
    if start is None or end is None:
        raise ValueError("tender totals need both a range start and end")
    is_date = (
        isinstance(start, datetime.date)
        and not isinstance(start, datetime.datetime)
    )
    if is_date:
        tz = timezone.get_current_timezone()
        start_dt = timezone.make_aware(
            datetime.datetime.combine(start, datetime.time.min), tz
        )
        end_dt = timezone.make_aware(
            datetime.datetime.combine(
                end + datetime.timedelta(days=1), datetime.time.min
            ),
            tz,
        )
        if end_dt <= start_dt:
            raise ValueError("range end must not be before its start")
        return start_dt, end_dt, True
    if end < start:
        raise ValueError("range end must not be before its start")
    return start, end, False


def tender_totals(start, end, salon=None):
    """Return :class:`TenderTotals` for completed payments in range.

    ``start``/``end`` are datetimes (inclusive range) or dates
    (whole days, inclusive). When ``salon`` is given, only payments
    on that salon's sales count; otherwise all salons are included.

    Every ``Payment.Method`` appears in ``by_method``, with
    ``Decimal('0.00')`` for methods with no completed payments —
    so an empty range returns zeros, not an empty mapping.
    Read-only: nothing is created, updated, or deleted.
    """
    start_bound, end_bound, is_date_range = _as_bounds(start, end)
    payments = Payment.objects.filter(
        status=Payment.Status.COMPLETED,
    ).exclude(sale__status=Sale.Status.VOIDED)
    if is_date_range:
        payments = payments.filter(
            created_at__gte=start_bound, created_at__lt=end_bound
        )
    else:
        payments = payments.filter(
            created_at__gte=start_bound, created_at__lte=end_bound
        )
    if salon is not None:
        payments = payments.filter(sale__salon=salon)

    rows = (
        payments.values("method")
        .annotate(amount=Sum("amount"), n=Count("id"))
        .order_by("method")
    )
    by_method = {method: _ZERO for method in Payment.Method.values}
    count = 0
    for row in rows:
        by_method[row["method"]] = Decimal(row["amount"]).quantize(_CENTS)
        count += row["n"]
    total = sum(by_method.values(), _ZERO).quantize(_CENTS)
    return TenderTotals(
        by_method=by_method, total=total, count=count, start=start, end=end
    )


def totals_by_tender(start, end, salon=None):
    """Return just ``{method: Decimal}`` (all methods, zeros filled)."""
    return tender_totals(start, end, salon=salon).by_method
