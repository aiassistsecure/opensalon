"""Insights service functions: figures derived from salon records.

Backend only — no views, templates, or UI. Nothing here is stored:
each figure is computed from the rows that own the fact —
``Sale`` / ``SaleItem`` rows for revenue, ``Appointment`` rows plus
the price book (``ServicePrice``) for future booked value.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import F, Sum
from django.utils import timezone

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from saloncore.models import ServicePrice

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class RevenueSplit:
    """Revenue for one inclusive date window, split by item kind.

    ``service`` sums line totals of ``SaleItem.Kind.SERVICE`` items,
    ``retail`` sums ``SaleItem.Kind.PRODUCT`` items (retail is the
    insights name for product sales), and ``total`` is their sum.
    ``start_date`` / ``end_date`` are the inclusive window bounds in
    the salon's timezone.
    """

    service: Decimal
    retail: Decimal
    total: Decimal
    start_date: date
    end_date: date
    days: int = 7


def _salon_tz(salon):
    try:
        return ZoneInfo(salon.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def last_7_days_revenue_split(salon, *, today=None):
    """Return the last 7 days' revenue split for ``salon``.

    The window is the 7 calendar days ending on ``today`` (default:
    today in the salon's timezone), inclusive at both ends, judged
    in the salon's timezone. Only completed sales count as revenue:
    open and voided sales are excluded. A sale belongs to the day of
    its ``completed_at`` when set, otherwise its ``created_at``.

    Returns a :class:`RevenueSplit` with Decimal amounts; a salon
    with no qualifying sales gets zeroes, never None.
    """
    tz = _salon_tz(salon)
    if today is None:
        today = timezone.now().astimezone(tz).date()
    start_date = today - timedelta(days=6)

    items = SaleItem.objects.filter(
        sale__salon=salon,
        sale__status=Sale.Status.COMPLETED,
    )
    totals = {SaleItem.Kind.SERVICE: ZERO, SaleItem.Kind.PRODUCT: ZERO}
    start_dt = datetime.combine(start_date, time.min, tzinfo=tz)
    end_dt = datetime.combine(today + timedelta(days=1), time.min, tzinfo=tz)
    in_window = items.filter(
        sale__completed_at__gte=start_dt,
        sale__completed_at__lt=end_dt,
    ) | items.filter(
        sale__completed_at__isnull=True,
        sale__created_at__gte=start_dt,
        sale__created_at__lt=end_dt,
    )
    rows = in_window.values("kind").annotate(
        amount=Sum(F("unit_price") * F("quantity"))
    )
    for row in rows:
        if row["kind"] in totals and row["amount"] is not None:
            totals[row["kind"]] = row["amount"]

    service = totals[SaleItem.Kind.SERVICE]
    retail = totals[SaleItem.Kind.PRODUCT]
    return RevenueSplit(
        service=service,
        retail=retail,
        total=service + retail,
        start_date=start_date,
        end_date=today,
        days=7,
    )


@dataclass(frozen=True)
class FutureDayValue:
    """Booked value for one calendar day in the salon's timezone."""

    day: date
    value: Decimal
    count: int


@dataclass(frozen=True)
class FutureAppointmentsValue:
    """Total value of all future, non-cancelled appointments.

    ``total`` / ``count`` cover every qualifying appointment from
    ``as_of`` onward, with no upper bound. ``days`` is the per-day
    breakdown for the next 7 calendar days only (``start_date``
    through ``end_date``, in the salon's timezone), so appointments
    further out count toward the total but appear in no day entry.
    """

    total: Decimal
    count: int
    as_of: datetime
    start_date: date
    end_date: date
    days: tuple


def future_appointments_value(salon, as_of=None):
    """Return the value of ``salon``'s future appointments.

    An appointment qualifies when it belongs to the salon (via its
    staff member), starts at or after ``as_of`` (default: now), and
    is not cancelled — the same non-cancelled rule the day book and
    availability apply.

    An appointment's price is the price book's one source of truth:
    the active ``ServicePrice`` for its service at its staff member's
    staff level. Nothing is copied onto the appointment. An
    appointment with no such price (staff member has no level, or no
    active price row for the service at that level) counts toward
    ``count`` but contributes zero to the value.

    Days are judged in the salon's timezone. Returns a
    :class:`FutureAppointmentsValue`; a salon with no qualifying
    appointments gets a zero total, never None.
    """
    if as_of is None:
        as_of = timezone.now()
    tz = _salon_tz(salon)
    start_date = as_of.astimezone(tz).date()
    end_date = start_date + timedelta(days=6)

    appointments = (
        Appointment.objects.filter(
            staff_member__salon=salon, start__gte=as_of,
        )
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("staff_member")
        .order_by("start")
    )
    prices = {
        (price.service_id, price.staff_level_id): price.amount
        for price in ServicePrice.objects.filter(
            service__category__salon=salon, active=True,
        )
    }

    total = ZERO
    by_day = {}
    for appt in appointments:
        amount = prices.get(
            (appt.service_id, appt.staff_member.staff_level_id), ZERO,
        )
        total += amount
        day = appt.start.astimezone(tz).date()
        if start_date <= day <= end_date:
            day_value, day_count = by_day.get(day, (ZERO, 0))
            by_day[day] = (day_value + amount, day_count + 1)

    days = []
    for offset in range(7):
        day = start_date + timedelta(days=offset)
        value, count = by_day.get(day, (ZERO, 0))
        days.append(FutureDayValue(day=day, value=value, count=count))
    return FutureAppointmentsValue(
        total=total,
        count=len(appointments),
        as_of=as_of,
        start_date=start_date,
        end_date=end_date,
        days=tuple(days),
    )
