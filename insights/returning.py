"""New-vs-returning revenue split: completed sales by client history.

Backend only — no views, templates, or UI. Nothing here is stored:
each figure is computed read-only from the rows that own the fact —
``Sale`` / ``SaleItem`` rows for revenue, as in
:mod:`insights.services`, and ``Sale`` / ``Appointment`` rows for
client history.

Attribution rule (the one source of truth for this split)
----------------------------------------------------------
The client link is direct and real, not inferred:

* ``Sale.client`` is a nullable foreign key to ``clients.Client``
  — that, and only that, links a sale to a client. No appointment
  matching, name matching, or any other heuristic is used to
  invent a client for a sale (contrast
  :mod:`insights.staff_revenue`, which needs an appointment
  heuristic because no direct staff link exists on a sale; here
  the direct link does exist). ``Receipt`` carries no client link
  at all and plays no part here.
* A sale counts only when it is completed (``Sale.Status``
  completed — open and voided sales never count) and its effective
  date falls in the window. A sale belongs to the day of its
  ``completed_at`` when set, otherwise its ``created_at``, judged
  in the salon's timezone — the established revenue attribution in
  ``insights.services``. Revenue is the sum of its ``SaleItem``
  line totals (all kinds), from the items grouped by sale, as in
  :mod:`insights.staff_revenue`.

Classification is per client, for the whole window:

* A client's *first-ever* moment at this salon is the earliest of
  (a) the effective moment (``completed_at``, else ``created_at``)
  of any completed sale linked to that client at this salon, and
  (b) the ``start`` of any completed appointment
  (``Appointment.Status.COMPLETED`` — booked, cancelled, no-show
  and every other status do not count) for that client at this
  salon (via ``staff_member__salon``). Both histories are scoped
  to this salon: activity at another salon never counts.
* *Returning*: the client's first-ever moment predates the window
  start. Every completed sale of theirs in the window is
  returning revenue.
* *New*: the client's first-ever moment falls within the window
  (it cannot be later — the window sale itself is one of the
  candidate moments). Every completed sale of theirs in the
  window is new revenue, including later ones in the same window.
* *Unattributed*: the sale has no client link
  (``Sale.client`` is null), or its linked client belongs to a
  different salon (an inconsistent link is never guessed at).
  Such sales are bucketed explicitly, never attributed.

The three buckets sum exactly to the window's total completed
sale revenue.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Q

from bookings.models import Appointment
from checkout.models import Sale, SaleItem

from .services import ZERO, _as_date, _salon_tz

UNATTRIBUTED_NAME = "Unattributed"


@dataclass(frozen=True)
class ReturningRevenue:
    """New-vs-returning revenue split for one inclusive window.

    Amounts are Decimal; counts are the number of completed sales
    in each bucket. ``total`` is
    ``returning_revenue + new_revenue + unattributed_revenue`` and
    ``total_sale_count`` the sum of the three counts.
    ``start_date`` / ``end_date`` are the inclusive window bounds
    (salon-local dates).
    """

    start_date: date
    end_date: date
    returning_revenue: Decimal
    new_revenue: Decimal
    unattributed_revenue: Decimal
    total: Decimal
    returning_sale_count: int
    new_sale_count: int
    unattributed_sale_count: int

    @property
    def returning(self):
        return self.returning_revenue

    @property
    def new(self):
        return self.new_revenue

    @property
    def unattributed(self):
        return self.unattributed_revenue

    @property
    def total_revenue(self):
        return self.total

    @property
    def total_sale_count(self):
        return (
            self.returning_sale_count + self.new_sale_count
            + self.unattributed_sale_count
        )


# Aliases: the same result under other natural names.
NewVsReturningRevenue = ReturningRevenue
ReturningRevenueSplit = ReturningRevenue


def _first_ever_moments(salon, client_ids):
    """Map client_id -> earliest completed sale/appointment moment."""
    firsts = {}
    sales = Sale.objects.filter(
        salon=salon, status=Sale.Status.COMPLETED,
        client_id__in=client_ids,
    ).values("client_id", "completed_at", "created_at")
    for row in sales:
        stamp = row["completed_at"] or row["created_at"]
        if stamp is None:
            continue
        current = firsts.get(row["client_id"])
        if current is None or stamp < current:
            firsts[row["client_id"]] = stamp
    appointments = Appointment.objects.filter(
        staff_member__salon=salon,
        status=Appointment.Status.COMPLETED,
        client_id__in=client_ids,
    ).values("client_id", "start")
    for row in appointments:
        stamp = row["start"]
        if stamp is None:
            continue
        current = firsts.get(row["client_id"])
        if current is None or stamp < current:
            firsts[row["client_id"]] = stamp
    return firsts


def new_vs_returning_revenue(salon, start, end):
    """Return the new-vs-returning split for ``salon`` in a window.

    ``start`` / ``end`` are inclusive bounds (``date`` objects, or
    ``datetime`` objects judged by their date in the salon's
    timezone, as in :func:`insights.services.busiest_days`).
    Attribution follows the rule in this module's docstring.

    Returns a :class:`ReturningRevenue`; a window with no
    qualifying sales — or a reversed window (``end`` before
    ``start``) — returns zeroes with the bounds as given, never
    ``None``. Money is Decimal throughout, never None.
    """
    tz = _salon_tz(salon)
    start_date = _as_date(start, tz)
    end_date = _as_date(end, tz)
    empty = ReturningRevenue(
        start_date=start_date, end_date=end_date,
        returning_revenue=ZERO, new_revenue=ZERO,
        unattributed_revenue=ZERO, total=ZERO,
        returning_sale_count=0, new_sale_count=0,
        unattributed_sale_count=0,
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

    client_ids = {
        sale.client_id for sale, _ in by_sale.values()
        if sale.client_id is not None
        and sale.client is not None
        and sale.client.salon_id == salon.pk
    }
    firsts = _first_ever_moments(salon, client_ids) if client_ids else {}

    # bucket name -> [revenue, sale_count]
    buckets = {
        "returning": [ZERO, 0],
        "new": [ZERO, 0],
        "unattributed": [ZERO, 0],
    }
    for sale, sale_items in by_sale.values():
        if (
            sale.client_id is None
            or sale.client is None
            or sale.client.salon_id != salon.pk
            or sale.client_id not in firsts
        ):
            bucket = buckets["unattributed"]
        elif firsts[sale.client_id] < start_dt:
            bucket = buckets["returning"]
        else:
            bucket = buckets["new"]
        for item in sale_items:
            bucket[0] += item.line_total
        bucket[1] += 1

    returning, new, unattributed = (
        buckets["returning"], buckets["new"], buckets["unattributed"]
    )
    return ReturningRevenue(
        start_date=start_date, end_date=end_date,
        returning_revenue=returning[0], new_revenue=new[0],
        unattributed_revenue=unattributed[0],
        total=returning[0] + new[0] + unattributed[0],
        returning_sale_count=returning[1], new_sale_count=new[1],
        unattributed_sale_count=unattributed[1],
    )


# Aliases: the same service under other natural names.
returning_revenue_split = new_vs_returning_revenue
revenue_by_new_vs_returning = new_vs_returning_revenue
get_new_vs_returning_revenue = new_vs_returning_revenue
