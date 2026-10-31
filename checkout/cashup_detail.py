"""Read-only cashup detail report service for checkout.

Backend only — no views, templates, or UI.

Where :mod:`checkout.cashup` stores an immutable close-out
snapshot of completed-payment totals, and
:mod:`checkout.refund_report` reports refunds alone, this
service answers the fuller close-out question for one salon
over an inclusive date range, broken down per tender:

* ``gross`` — completed payments on completed sales in range.
  Voided sales are excluded from gross entirely: a void is a
  reversal, not a taking.
* ``refunds`` — refunds recorded in range on completed sales
  (a refund belongs to the range of its own ``created_at``,
  when the money went back, as in :mod:`checkout.refund_report`).
* ``voids`` — completed payments on sales that are voided,
  reported per tender so the excluded amount stays auditable.
  Because voided sales never enter gross, voids are NOT
  subtracted again in ``net``.
* ``net`` — ``gross - refunds`` per tender, and in total.

Attribution: a payment (gross or void) belongs to the range
of its own ``created_at``; dates are judged as whole local
days in the salon's timezone (``Salon.timezone``, falling
back to UTC), following :mod:`checkout.refund_report`.

Nothing is stored and nothing is mutated: ``Sale``,
``Payment``, and ``Refund`` rows are only read, and they stay
the one source of truth. An empty range is all zeroes, never
``None``, and every core tender appears in ``by_tender``
(zero-filled). Core stays provider-agnostic: grouping is by
the core ``Payment.Method`` / ``Refund.tender`` slug only —
no provider name, field, or SDK anywhere.
"""
import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Count, Sum

from .models import Payment, Refund, Sale

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class TenderDetail:
    """Gross / refunds / voids / net for one tender slug."""

    tender: str
    gross: Decimal = _ZERO
    refunds: Decimal = _ZERO
    voids: Decimal = _ZERO
    net: Decimal = _ZERO
    payment_count: int = 0
    refund_count: int = 0
    void_count: int = 0

    @property
    def method(self):
        return self.tender

    @property
    def gross_sales(self):
        return self.gross

    @property
    def refund_total(self):
        return self.refunds

    @property
    def void_total(self):
        return self.voids


@dataclass(frozen=True)
class CashupDetail:
    """One salon's cashup detail across an inclusive date range.

    ``by_tender`` maps every core tender slug to its
    :class:`TenderDetail`; the top-level ``gross`` / ``refunds``
    / ``voids`` / ``net`` are the sums across tenders.
    """

    salon: object
    date_from: datetime.date
    date_to: datetime.date
    gross: Decimal = _ZERO
    refunds: Decimal = _ZERO
    voids: Decimal = _ZERO
    net: Decimal = _ZERO
    by_tender: dict = field(default_factory=dict)

    @property
    def salon_id(self):
        return getattr(self.salon, "pk", self.salon)

    @property
    def start(self):
        return self.date_from

    @property
    def end(self):
        return self.date_to

    @property
    def gross_sales(self):
        return self.gross

    @property
    def refund_total(self):
        return self.refunds

    @property
    def void_total(self):
        return self.voids

    def __getitem__(self, tender):
        return self.by_tender[tender]


def _salon_tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_day(value, tz, label):
    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            return value.astimezone(tz).date()
        return value.date()
    if isinstance(value, datetime.date):
        return value
    raise ValueError(f"cashup detail needs a date for `{label}`")


def _aggregate(queryset, key):
    """Return ``{key_value: (Decimal amount, count)}`` for a queryset."""
    rows = (
        queryset.values(key)
        .annotate(amount=Sum("amount"), n=Count("id"))
        .order_by(key)
    )
    out = {}
    for row in rows:
        if row["amount"] is not None:
            out[row[key]] = (
                Decimal(row["amount"]).quantize(_CENTS),
                row["n"],
            )
    return out


def cashup_detail(salon, date_from, date_to):
    """Return the :class:`CashupDetail` for ``salon`` over a range.

    ``date_from`` / ``date_to`` are dates (or datetimes, judged
    in the salon's timezone); both ends are inclusive whole
    local days. Only that salon's records count. Read-only.
    """
    if salon is None:
        raise ValueError("cashup_detail needs a salon")
    tz = _salon_tz(salon)
    start_day = _as_day(date_from, tz, "date_from")
    end_day = _as_day(date_to, tz, "date_to")
    if end_day < start_day:
        raise ValueError("range end must not be before its start")
    start_dt = datetime.datetime.combine(
        start_day, datetime.time.min, tzinfo=tz
    )
    end_dt = start_dt + datetime.timedelta(
        days=(end_day - start_day).days + 1
    )
    window = {"created_at__gte": start_dt, "created_at__lt": end_dt}

    gross_map = _aggregate(
        Payment.objects.filter(
            sale__salon=salon,
            sale__status=Sale.Status.COMPLETED,
            status=Payment.Status.COMPLETED,
            **window,
        ),
        "method",
    )
    void_map = _aggregate(
        Payment.objects.filter(
            sale__salon=salon,
            sale__status=Sale.Status.VOIDED,
            status=Payment.Status.COMPLETED,
            **window,
        ),
        "method",
    )
    refund_map = _aggregate(
        Refund.objects.filter(
            sale__salon=salon,
            sale__status=Sale.Status.COMPLETED,
            **window,
        ),
        "tender",
    )

    by_tender = {}
    for tender in Payment.Method.values:
        gross, gross_n = gross_map.get(tender, (_ZERO, 0))
        refunds, refund_n = refund_map.get(tender, (_ZERO, 0))
        voids, void_n = void_map.get(tender, (_ZERO, 0))
        by_tender[tender] = TenderDetail(
            tender=tender,
            gross=gross,
            refunds=refunds,
            voids=voids,
            net=(gross - refunds).quantize(_CENTS),
            payment_count=gross_n,
            refund_count=refund_n,
            void_count=void_n,
        )

    def _total(attr):
        return sum(
            (getattr(d, attr) for d in by_tender.values()), _ZERO
        ).quantize(_CENTS)

    return CashupDetail(
        salon=salon,
        date_from=start_day,
        date_to=end_day,
        gross=_total("gross"),
        refunds=_total("refunds"),
        voids=_total("voids"),
        net=_total("net"),
        by_tender=by_tender,
    )
