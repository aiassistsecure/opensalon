"""Read-only refunds-by-day report service for checkout.

Backend only — no views, templates, or UI.

Answers, for one salon: how many refunds were recorded on a
local calendar day (or across a date range), what they total,
and how that splits by tender (``Refund.tender``, a core
``Payment.Method`` slug).

Day attribution follows the established pattern in
:mod:`checkout.summary`: the day is judged in the salon's
timezone (``Salon.timezone``, falling back to UTC) as a
half-open local window ``[day 00:00, next day 00:00)``. A refund
belongs to the day of its own ``created_at`` — the moment the
money was returned — not the day its sale completed.

Refunds only ever exist on completed sales
(:func:`checkout.refunds.record_refund` refuses every other
status, and a voided sale is already reversed). The queries
here filter to refunds on completed sales, so an impossible
refund row attached to a voided or open sale — should one ever
exist in the data — is never counted or double counted.

Nothing is stored here and nothing is mutated: the ``Refund``
rows are the one source of truth. An empty day or range is all
zeroes, never ``None``, and every core tender appears in
``by_tender`` / ``counts_by_tender`` (zero-filled).

Core stays provider-agnostic: grouping is by the core tender
slug only; no provider name, field, or SDK appears here.
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
class RefundsByDay:
    """One salon's refunds for one local calendar day."""

    salon: object
    day: datetime.date
    refund_count: int
    total: Decimal
    by_tender: dict = field(default_factory=dict)
    counts_by_tender: dict = field(default_factory=dict)

    @property
    def date(self):
        return self.day

    @property
    def salon_id(self):
        return getattr(self.salon, "pk", self.salon)

    @property
    def count(self):
        return self.refund_count

    @property
    def refund_total(self):
        return self.total

    def __getitem__(self, key):
        return self.by_tender[key]


@dataclass(frozen=True)
class RefundTotals:
    """One salon's refunds across an inclusive date range.

    ``by_day`` carries a :class:`RefundsByDay` for every day in
    the range (empty days zero-filled), in date order via
    ``days``; ``by_tender`` / ``counts_by_tender`` and
    ``refund_count`` / ``total`` are the range-wide aggregates.
    """

    salon: object
    date_from: datetime.date
    date_to: datetime.date
    refund_count: int
    total: Decimal
    by_tender: dict = field(default_factory=dict)
    counts_by_tender: dict = field(default_factory=dict)
    by_day: dict = field(default_factory=dict)

    @property
    def count(self):
        return self.refund_count

    @property
    def refund_total(self):
        return self.total

    @property
    def start(self):
        return self.date_from

    @property
    def end(self):
        return self.date_to

    @property
    def days(self):
        return [self.by_day[d] for d in sorted(self.by_day)]

    def __getitem__(self, key):
        return self.by_tender[key]


def _salon_tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_day(day, tz, label):
    if isinstance(day, datetime.datetime):
        if day.tzinfo is not None:
            return day.astimezone(tz).date()
        return day.date()
    if isinstance(day, datetime.date):
        return day
    raise ValueError(f"refund report needs a date for `{label}`")


def _empty_tenders():
    return {method: _ZERO for method in Payment.Method.values}


def _empty_counts():
    return {method: 0 for method in Payment.Method.values}


def _refunds_in_window(salon, start_dt, end_dt):
    return Refund.objects.filter(
        sale__salon=salon,
        sale__status=Sale.Status.COMPLETED,
        created_at__gte=start_dt,
        created_at__lt=end_dt,
    )


def _summarise(salon, day, refunds):
    rows = (
        refunds.values("tender")
        .annotate(amount=Sum("amount"), n=Count("id"))
        .order_by("tender")
    )
    by_tender = _empty_tenders()
    counts_by_tender = _empty_counts()
    count = 0
    for row in rows:
        if row["tender"] in by_tender and row["amount"] is not None:
            by_tender[row["tender"]] = Decimal(row["amount"]).quantize(_CENTS)
            counts_by_tender[row["tender"]] = row["n"]
            count += row["n"]
    total = sum(by_tender.values(), _ZERO).quantize(_CENTS)
    return RefundsByDay(
        salon=salon,
        day=day,
        refund_count=count,
        total=total,
        by_tender=by_tender,
        counts_by_tender=counts_by_tender,
    )


def refunds_by_day(salon, day):
    """Return the :class:`RefundsByDay` for ``salon`` on ``day``.

    ``day`` is a ``date`` (or a ``datetime``, judged by its date
    in the salon's timezone). Only that salon's refunds on
    completed sales count. Read-only.
    """
    if salon is None:
        raise ValueError("refunds_by_day needs a salon")
    tz = _salon_tz(salon)
    local_day = _as_day(day, tz, "day")
    start_dt = datetime.datetime.combine(
        local_day, datetime.time.min, tzinfo=tz
    )
    end_dt = start_dt + datetime.timedelta(days=1)
    return _summarise(
        salon, local_day, _refunds_in_window(salon, start_dt, end_dt)
    )


def refund_totals(salon, date_from, date_to):
    """Return :class:`RefundTotals` for ``salon`` over a range.

    ``date_from`` / ``date_to`` are dates (or datetimes, judged
    in the salon's timezone); both ends are inclusive whole
    local days. Read-only.
    """
    if salon is None:
        raise ValueError("refund_totals needs a salon")
    tz = _salon_tz(salon)
    start_day = _as_day(date_from, tz, "date_from")
    end_day = _as_day(date_to, tz, "date_to")
    if end_day < start_day:
        raise ValueError("range end must not be before its start")
    start_dt = datetime.datetime.combine(
        start_day, datetime.time.min, tzinfo=tz
    )
    end_dt = datetime.datetime.combine(
        end_day, datetime.time.min, tzinfo=tz
    ) + datetime.timedelta(days=1)
    refunds = _refunds_in_window(salon, start_dt, end_dt)

    overall = _summarise(salon, start_day, refunds)
    by_day = {}
    current = start_day
    while current <= end_day:
        day_start = datetime.datetime.combine(
            current, datetime.time.min, tzinfo=tz
        )
        day_end = day_start + datetime.timedelta(days=1)
        by_day[current] = _summarise(
            salon,
            current,
            refunds.filter(
                created_at__gte=day_start, created_at__lt=day_end
            ),
        )
        current += datetime.timedelta(days=1)
    return RefundTotals(
        salon=salon,
        date_from=start_day,
        date_to=end_day,
        refund_count=overall.refund_count,
        total=overall.total,
        by_tender=overall.by_tender,
        counts_by_tender=overall.counts_by_tender,
        by_day=by_day,
    )
