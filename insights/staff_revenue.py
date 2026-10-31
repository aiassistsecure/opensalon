"""Per-staff revenue: completed sales attributed to staff members.

Backend only — no views, templates, or UI. Nothing here is stored:
each figure is computed from the rows that own the fact —
``Sale`` / ``SaleItem`` rows for revenue, as in
:mod:`insights.services`.

Attribution rule (the one source of truth for staff revenue)
-------------------------------------------------------------
``SaleItem`` carries no staff link and ``Sale`` carries no
appointment link in the current models, so a sale is attributed
at *sale level* through its appointment:

* A sale counts only when it is completed (``Sale.Status``
  completed — open and voided sales never count, as in
  :func:`insights.services.last_7_days_revenue_split`) and its
  effective date falls in the window. A sale belongs to the day
  of its ``completed_at`` when set, otherwise its ``created_at``,
  judged in the salon's timezone — the established revenue
  attribution in ``insights.services``.
* Candidate appointments are the sale client's non-cancelled
  appointments at this salon (via staff member) starting on the
  sale's effective local day.
* When the sale has service items linked to a service, only
  candidates for one of those services can attribute it; the
  earliest such appointment (``start``, then ``pk``) wins. If no
  candidate matches the service, the sale is unattributed.
* When the sale has no service-linked item (e.g. a retail-only
  sale), it is attributed only when the candidates name exactly
  one distinct staff member; zero or several means unattributed.
* An attributed sale contributes *all* its items to that staff
  member: service items to ``service_revenue`` and product items
  to ``retail_revenue`` (retail is the insights name for product
  sales). ``sale_count`` counts each attributed sale once.
* Anything else — no client, no candidate appointment, a service
  mismatch, or an ambiguous retail-only day — is bucketed as
  unattributed, never guessed.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Q

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from team.models import StaffMember

from .services import ZERO, _as_date, _salon_tz

UNATTRIBUTED_NAME = "Unattributed"


@dataclass(frozen=True)
class StaffRevenue:
    """Revenue attributed to one staff member in a window.

    ``staff`` is the ``StaffMember`` (``None`` for the
    unattributed bucket, whose ``display_name`` is
    ``"Unattributed"``). Amounts are Decimal; ``total`` is
    ``service_revenue + retail_revenue`` and ``sale_count`` is
    the number of completed sales attributed to this row.
    """

    staff: StaffMember | None
    display_name: str
    service_revenue: Decimal
    retail_revenue: Decimal
    total: Decimal
    sale_count: int

    @property
    def staff_member(self):
        return self.staff

    @property
    def service(self):
        return self.service_revenue

    @property
    def retail(self):
        return self.retail_revenue


def _attribute_staff(sale, items, *, salon, tz, cache):
    """Return the staff member ``sale`` is attributed to, or None."""
    if sale.client_id is None:
        return None
    stamp = sale.completed_at or sale.created_at
    if stamp is None:
        return None
    day = stamp.astimezone(tz).date()
    key = (sale.client_id, day)
    if key not in cache:
        day_start = datetime.combine(day, time.min, tzinfo=tz)
        day_end = day_start + timedelta(days=1)
        cache[key] = list(
            Appointment.objects.filter(
                client_id=sale.client_id,
                staff_member__salon=salon,
                start__gte=day_start, start__lt=day_end,
            )
            .exclude(status=Appointment.Status.CANCELLED)
            .select_related("staff_member")
            .order_by("start", "pk")
        )
    candidates = cache[key]
    if not candidates:
        return None
    service_ids = {
        item.service_id for item in items
        if item.kind == SaleItem.Kind.SERVICE and item.service_id
    }
    if service_ids:
        for appt in candidates:
            if appt.service_id in service_ids:
                return appt.staff_member
        return None
    staff_ids = {appt.staff_member_id for appt in candidates}
    if len(staff_ids) == 1:
        return candidates[0].staff_member
    return None


def revenue_by_staff(salon, start, end):
    """Return per-staff revenue for ``salon`` in a date window.

    ``start`` / ``end`` are inclusive bounds (``date`` objects, or
    ``datetime`` objects judged by their date in the salon's
    timezone, as in :func:`insights.services.busiest_days`).
    Attribution follows the rule in this module's docstring.

    Returns a list of :class:`StaffRevenue` rows — one per staff
    member with at least one attributed completed sale — ordered
    by ``total`` descending, with ``display_name`` ascending as
    the tie-break. An unattributed row (``staff=None``) is
    included in the same ordering only when its total is
    non-zero. A window with no qualifying sales — or a reversed
    window (``end`` before ``start``) — returns an empty list.
    Money is Decimal throughout, never None.
    """
    tz = _salon_tz(salon)
    start_date = _as_date(start, tz)
    end_date = _as_date(end, tz)
    if end_date < start_date:
        return []
    start_dt = datetime.combine(start_date, time.min, tzinfo=tz)
    end_dt = datetime.combine(
        end_date + timedelta(days=1), time.min, tzinfo=tz
    )

    items = (
        SaleItem.objects.filter(
            sale__salon=salon, sale__status=Sale.Status.COMPLETED,
        )
        .filter(
            Q(sale__completed_at__gte=start_dt,
              sale__completed_at__lt=end_dt)
            | Q(sale__completed_at__isnull=True,
                sale__created_at__gte=start_dt,
                sale__created_at__lt=end_dt)
        )
        .select_related("sale", "sale__client")
        .order_by("sale_id", "id")
    )
    by_sale = {}
    for item in items:
        by_sale.setdefault(item.sale_id, (item.sale, []))[1].append(item)

    # key: staff pk or None -> [staff, service, retail, sale_count]
    buckets = {}
    cache = {}
    for sale, sale_items in by_sale.values():
        staff = _attribute_staff(
            sale, sale_items, salon=salon, tz=tz, cache=cache,
        )
        key = staff.pk if staff is not None else None
        bucket = buckets.setdefault(key, [staff, ZERO, ZERO, 0])
        for item in sale_items:
            if item.kind == SaleItem.Kind.SERVICE:
                bucket[1] += item.line_total
            elif item.kind == SaleItem.Kind.PRODUCT:
                bucket[2] += item.line_total
        bucket[3] += 1

    rows = []
    for staff, service, retail, count in buckets.values():
        total = service + retail
        if staff is None and total == ZERO:
            continue
        rows.append(StaffRevenue(
            staff=staff,
            display_name=(
                staff.display_name if staff is not None
                else UNATTRIBUTED_NAME
            ),
            service_revenue=service,
            retail_revenue=retail,
            total=total,
            sale_count=count,
        ))
    rows.sort(key=lambda row: (-row.total, row.display_name))
    return rows
