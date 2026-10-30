"""Cashup (close-out) service for checkout.

A cashup totals a period's takings from the payments already
recorded against a salon's sales, grouped by tender (payment
method), and stores the result as an immutable ``Cashup``
snapshot.

Semantics (deliberate, per the salon's own usage): a cashup is a
snapshot, not a lock. Closing more than once a day is fine, a
cashup never hard-locks the day, and it never blocks, alters, or
consumes later sales — a sale recorded after a cashup is simply
included by the next cashup whose period covers it.

Only completed payments count toward takings: pending and failed
payments moved no money, and refunded payments are excluded here
(their original completed payment is what was taken). Core stays
provider-agnostic: grouping is by the core ``Payment.method``
tender slug only, with no provider field, name, or SDK anywhere.
"""
from decimal import Decimal

from django.db.models import Sum

from .models import Cashup, Payment


def _period_payments(salon, since, until):
    payments = Payment.objects.filter(
        sale__salon=salon,
        status=Payment.Status.COMPLETED,
        created_at__gte=since,
        created_at__lte=until,
    )
    return payments


def compute_tender_totals(salon, since, until):
    """Return ``{method: Decimal}`` for completed payments in period.

    Dry run: records nothing. Methods with no completed payments
    in the period are omitted.
    """
    rows = (
        _period_payments(salon, since, until)
        .values("method")
        .annotate(amount=Sum("amount"))
        .order_by("method")
    )
    cents = Decimal("0.01")
    return {
        row["method"]: Decimal(row["amount"]).quantize(cents) for row in rows
    }


def run_cashup(salon, since, until, note=""):
    """Run a cashup for ``salon`` over [``since``, ``until``].

    Stores and returns a ``Cashup`` snapshot whose ``tender_totals``
    map each payment method to its period total (as a string, to
    preserve exact decimal values) and whose ``total`` is their
    sum. Raises ``ValueError`` if the period is inverted. Taking a
    cashup changes no sale or payment, so it may be run any number
    of times, including several times on the same day.
    """
    if since is None or until is None:
        raise ValueError("a cashup needs both a period start and end")
    if until < since:
        raise ValueError("cashup period end must not be before its start")
    totals = compute_tender_totals(salon, since, until)
    total = sum(totals.values(), Decimal("0.00")).quantize(Decimal("0.01"))
    return Cashup.objects.create(
        salon=salon,
        period_start=since,
        period_end=until,
        tender_totals={method: str(amount) for method, amount in totals.items()},
        total=total,
        note=note or "",
    )
