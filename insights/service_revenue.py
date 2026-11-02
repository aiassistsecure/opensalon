"""Per-service revenue: completed service sale items by service.

Backend only — no views, templates, or UI. Nothing here is stored:
each figure is computed from the ``Sale`` / ``SaleItem`` rows that
own the fact, as in :mod:`insights.services`.

Definitions (the contract of this module)
-----------------------------------------
* Only ``SaleItem.Kind.SERVICE`` items on completed sales count
  (open and voided sales never count, as in
  :func:`insights.services.last_7_days_revenue_split`). A sale
  belongs to the day of its ``completed_at`` when set, otherwise
  its ``created_at``, judged in the salon's timezone; the range
  is inclusive at both ends.
* Rows group by linked service when present (two distinct
  services never merge, even with the same name); unlinked items
  group by their verbatim ``description`` snapshot, otherwise
  ``"Unknown service"`` — as in :mod:`insights.popularity`.
* ``revenue`` is the Decimal sum of line totals, never a float
  and never ``None``. ``quantity`` sums quantities, ``line_count``
  counts items, ``sale_count`` counts distinct contributing sales.
* Revenue per hour: ``duration_minutes`` is the linked service's
  ``Service.total_minutes`` (saloncore). ``total_duration_minutes``
  is ``duration_minutes * quantity`` — service time actually sold.
  ``revenue_per_hour`` is ``revenue`` over that time in hours,
  quantized to cents. Zero/unknown duration gives ``None`` —
  never a divide-by-zero, never a float.
* Rows rank by ``revenue`` descending, then service name ascending.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q

from checkout.models import Sale, SaleItem

from .services import ZERO, _as_date, _salon_tz

UNKNOWN_SERVICE_NAME = "Unknown service"
CENTS = Decimal("0.01")


@dataclass(frozen=True)
class ServiceRevenue:
    """Revenue for one service in an inclusive window.

    ``service`` is the linked ``Service`` (``None`` for
    snapshot-only rows); ``revenue_per_hour`` is a Decimal or
    ``None`` when duration is zero/unknown.
    """

    service: object | None
    service_name: str
    revenue: Decimal
    quantity: int
    line_count: int
    sale_count: int
    duration_minutes: int | None
    total_duration_minutes: int | None
    revenue_per_hour: Decimal | None

    @property
    def service_id(self):
        return self.service.pk if self.service is not None else None

    @property
    def name(self):
        return self.service_name

    @property
    def display_name(self):
        return self.service_name

    @property
    def total(self):
        return self.revenue


# Aliases: the same result under other natural names.
ServiceRevenueRow = ServiceRevenue
RevenueByService = ServiceRevenue


def revenue_by_service(salon, start=None, end=None, *,
                       start_date=None, end_date=None,
                       since=None, until=None):
    """Return per-service revenue for ``salon`` over a range.

    ``start`` / ``end`` are inclusive bounds (``date`` or
    ``datetime`` judged in the salon's timezone, as in
    :mod:`insights.staff_revenue`); ``start_date`` / ``end_date``
    and ``since`` / ``until`` are keyword aliases. Returns
    :class:`ServiceRevenue` rows ranked by revenue descending;
    an empty or reversed range returns ``[]``, never ``None``.
    """
    if start is None:
        start = start_date if start_date is not None else since
    if end is None:
        end = end_date if end_date is not None else until
    if start is None or end is None:
        raise TypeError(
            "revenue_by_service requires a start and an end date"
        )
    tz = _salon_tz(salon)
    start_day = _as_date(start, tz)
    end_day = _as_date(end, tz)
    if end_day < start_day:
        return []
    start_dt = datetime.combine(start_day, time.min, tzinfo=tz)
    end_dt = datetime.combine(end_day + timedelta(days=1), time.min,
                              tzinfo=tz)
    items = (
        SaleItem.objects.filter(
            sale__salon=salon, sale__status=Sale.Status.COMPLETED,
            kind=SaleItem.Kind.SERVICE,
        )
        .filter(
            Q(sale__completed_at__gte=start_dt,
              sale__completed_at__lt=end_dt)
            | Q(sale__completed_at__isnull=True,
                sale__created_at__gte=start_dt,
                sale__created_at__lt=end_dt)
        )
        .select_related("sale", "service")
        .order_by("sale_id", "id")
    )
    # key: ("service", pk) or ("snapshot", name)
    # -> [service, name, revenue, quantity, lines, {sale ids}]
    buckets = {}
    for item in items:
        if item.service_id is not None:
            key = ("service", item.service_id)
            service = item.service
            name = (service.name if service is not None
                    else item.description) or UNKNOWN_SERVICE_NAME
        else:
            name = item.description or UNKNOWN_SERVICE_NAME
            key = ("snapshot", name)
            service = None
        bucket = buckets.setdefault(
            key, [service, name, ZERO, 0, 0, set()])
        bucket[2] += item.line_total
        bucket[3] += item.quantity
        bucket[4] += 1
        bucket[5].add(item.sale_id)
    rows = []
    for service, name, revenue, quantity, lines, sale_ids in (
            buckets.values()):
        if service is not None:
            duration = service.total_minutes
        else:
            duration = None
        if duration:
            total_duration = duration * quantity
            per_hour = (revenue * 60 / total_duration).quantize(
                CENTS, rounding=ROUND_HALF_UP)
        else:
            total_duration = duration * quantity if duration else None
            per_hour = None
        rows.append(ServiceRevenue(
            service=service, service_name=name, revenue=revenue,
            quantity=quantity, line_count=lines,
            sale_count=len(sale_ids), duration_minutes=duration,
            total_duration_minutes=total_duration,
            revenue_per_hour=per_hour,
        ))
    rows.sort(key=lambda row: (-row.revenue, row.service_name))
    return rows


# Aliases: the same service under other natural names.
service_revenue = revenue_by_service
get_service_revenue = revenue_by_service
