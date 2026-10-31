"""Per-client value summary: settled revenue per client.

Backend only — no views, templates, or UI. Nothing here is stored
or mutated: each figure is computed read-only from the
``Sale`` / ``SaleItem`` rows in the checkout app, which are the
one source of truth for revenue, as in :mod:`insights.services`,
:mod:`insights.staff_revenue`, and :mod:`insights.returning`.

Settled-sale definition (reused verbatim, not reinvented)
----------------------------------------------------------
* A sale counts only when it is completed (``Sale.Status``
  completed — open and voided sales never count, as in
  :func:`insights.services.last_7_days_revenue_split`) and its
  effective date falls in the window. A sale belongs to the day
  of its ``completed_at`` when set, otherwise its ``created_at``,
  judged in the salon's timezone.
* Revenue is the sum of a sale's ``SaleItem`` line totals (all
  kinds), from the items grouped by sale, as in
  :mod:`insights.staff_revenue`. A completed sale with no items
  therefore contributes no row and is not counted.

Client attribution and the unattributed bucket
----------------------------------------------
* ``Sale.client`` is a nullable foreign key to ``clients.Client``
  — that, and only that, links a sale to a client. No appointment
  matching, name matching, or any other heuristic is used.
* Sales with no client (``Sale.client`` is null), and sales whose
  linked client belongs to a different salon (an inconsistent
  link is never guessed at), are EXCLUDED from the per-client
  rows. Following the unattributed precedent in
  :mod:`insights.returning` (L7-M5), their revenue is not dropped:
  it is exposed separately on the result as
  ``unattributed_total`` with ``unattributed_sale_count``, and
  ``rows' totals + unattributed_total == total``.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Q

from checkout.models import Sale, SaleItem
from clients.models import Client

from .services import ZERO, _as_date, _salon_tz

UNATTRIBUTED_NAME = "Unattributed"


@dataclass(frozen=True)
class ClientValue:
    """Settled revenue for one client in an inclusive window.

    ``client`` is the ``Client``; ``total`` is the sum of that
    client's completed-sale item line totals in the window and
    ``sale_count`` is the number of those sales.
    """

    client: Client
    total: Decimal
    sale_count: int

    @property
    def client_id(self):
        return self.client.pk if self.client is not None else None

    @property
    def display_name(self):
        return str(self.client) if self.client is not None else ""

    @property
    def revenue(self):
        return self.total

    @property
    def value(self):
        return self.total


# Aliases: the same row under other natural names.
ClientValueRow = ClientValue
ValueByClient = ClientValue


@dataclass(frozen=True)
class ClientValueSummary:
    """Ranked per-client rows plus the unattributed bucket.

    ``rows`` is a tuple of :class:`ClientValue`, ranked by
    ``total`` descending, then ``sale_count`` descending, then
    client name ascending. ``total`` / ``sale_count`` cover the
    attributed rows only; the excluded no-client (or
    cross-salon-client) sales are carried separately in
    ``unattributed_total`` / ``unattributed_sale_count``, so
    ``total + unattributed_total`` is the window's full
    completed-sale revenue. Iterating the summary yields ``rows``.
    """

    rows: tuple
    unattributed_total: Decimal
    unattributed_sale_count: int
    total: Decimal
    sale_count: int
    start_date: date
    end_date: date

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    @property
    def unattributed(self):
        return self.unattributed_total

    @property
    def grand_total(self):
        return self.total + self.unattributed_total


def client_value(salon, start, end):
    """Return the per-client value summary for ``salon``.

    ``start`` / ``end`` are inclusive bounds (``date`` objects, or
    ``datetime`` objects judged by their date in the salon's
    timezone, as in :func:`insights.services.busiest_days`).
    Definitions are in this module's docstring.

    Returns a :class:`ClientValueSummary`. A window with no
    qualifying sales — or a reversed window (``end`` before
    ``start``) — returns empty rows and zeroes, never ``None``.
    Money is Decimal throughout, never None.
    """
    tz = _salon_tz(salon)
    start_date = _as_date(start, tz)
    end_date = _as_date(end, tz)
    empty = ClientValueSummary(
        rows=(), unattributed_total=ZERO, unattributed_sale_count=0,
        total=ZERO, sale_count=0,
        start_date=start_date, end_date=end_date,
    )
    if end_date < start_date:
        return empty
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
    if not by_sale:
        return empty

    # client pk -> [client, total, sale_count]
    buckets = {}
    unattributed_total = ZERO
    unattributed_count = 0
    for sale, sale_items in by_sale.values():
        sale_total = sum(
            (item.line_total for item in sale_items), ZERO
        )
        if (
            sale.client_id is None
            or sale.client is None
            or sale.client.salon_id != salon.pk
        ):
            unattributed_total += sale_total
            unattributed_count += 1
            continue
        bucket = buckets.setdefault(
            sale.client_id, [sale.client, ZERO, 0]
        )
        bucket[1] += sale_total
        bucket[2] += 1

    rows = [
        ClientValue(client=client, total=total, sale_count=count)
        for client, total, count in buckets.values()
    ]
    rows.sort(key=lambda row: (
        -row.total, -row.sale_count, row.display_name,
    ))
    return ClientValueSummary(
        rows=tuple(rows),
        unattributed_total=unattributed_total,
        unattributed_sale_count=unattributed_count,
        total=sum((row.total for row in rows), ZERO),
        sale_count=sum(row.sale_count for row in rows),
        start_date=start_date, end_date=end_date,
    )


# Aliases: the same service under other natural names.
value_by_client = client_value
revenue_by_client = client_value
get_client_value = client_value
client_value_summary = client_value
