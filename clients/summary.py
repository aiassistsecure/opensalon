"""Client visit summary service.

Pure service module — no views, no templates, no UI. Read-only:
nothing here creates, updates, or deletes a row.

:func:`client_visit_summary` answers, for one client:

* ``total_visits`` — count of that client's appointments in
  ``bookings.Appointment`` excluding cancelled appointments.
  Every other status counts (booked, confirmed, arrived,
  in-service, completed, no-show) and there is no time filter:
  this is the literal non-cancelled total, with past/future
  detail carried separately by ``last_visit`` /
  ``next_appointment`` below.
* ``last_visit`` — start of the most recent non-cancelled
  appointment with ``start < now`` (``None`` if there is none).
* ``next_appointment`` — the soonest non-cancelled appointment
  with ``start >= now``, as the ``Appointment`` itself (``None``
  if there is none). An appointment starting exactly at ``now``
  counts as upcoming, matching ``bookings.client_history``.
* ``lifetime_spend`` — sum of that client's non-voided sale
  totals in ``checkout.Sale``.
* Note counts, kept distinct (see below).

Lifetime spend — source of truth: ``Sale`` HAS a direct client
link, ``checkout.Sale.client`` (FK to ``clients.Client``,
``related_name="sales"``), so spend is attributed through that
real FK only. A sale's total is never stored; it is the sum of
its items' line totals (``unit_price * quantity``), the same
derivation as :attr:`checkout.Sale.total`. Voided sales are
excluded entirely; every other status counts. No
appointment-linked attribution is used — ``Sale`` carries no
appointment link, and inventing one would risk double-counting
a sale already attributed by its client FK.

Two kinds of notes, never blurred:

* ``record_note_count`` counts ``clients.ClientNote`` — persistent
  notes on the client record, across visits.
* ``appointment_note_count`` counts ``bookings.AppointmentNote``
  rows attached to this client's appointments — notes for one
  appointment only.

They are reported as separate fields only; there is deliberately
no combined note total.

Isolation: every query filters on exactly the given client, so
another client's appointments, sales, or notes never count — not
even a client in the same salon.

Core stays provider-agnostic: no payment-provider SDK, field, or
name appears here.
"""
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import F, Sum
from django.utils import timezone

from bookings.models import Appointment, AppointmentNote
from checkout.models import Sale, SaleItem
from clients.models import ClientNote

__all__ = ["ClientVisitSummary", "client_visit_summary", "client_summary"]

_CENTS = Decimal("0.01")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class ClientVisitSummary:
    """One client's visit summary. See the module docstring."""

    client: object
    total_visits: int
    last_visit: object = None  # datetime | None
    next_appointment: object = None  # Appointment | None
    lifetime_spend: Decimal = _ZERO
    record_note_count: int = 0
    appointment_note_count: int = 0

    @property
    def client_id(self):
        return getattr(self.client, "pk", self.client)

    @property
    def last_visit_date(self):
        """Date of ``last_visit`` (``None`` when there was none)."""
        return self.last_visit.date() if self.last_visit else None

    @property
    def last_appointment(self):
        return self.last_visit

    @property
    def next_visit(self):
        return self.next_appointment

    @property
    def next_appointment_start(self):
        return self.next_appointment.start if self.next_appointment else None

    @property
    def total_spend(self):
        return self.lifetime_spend

    @property
    def lifetime_total(self):
        return self.lifetime_spend

    @property
    def client_record_note_count(self):
        return self.record_note_count

    @property
    def client_note_count(self):
        return self.record_note_count


def client_visit_summary(client, now=None):
    """Return the :class:`ClientVisitSummary` for ``client``.

    Args:
        client: a ``clients.Client`` instance.
        now: reference instant splitting last visit from next
            appointment; defaults to ``timezone.now()``. Pass an
            aware datetime in tests for a deterministic boundary.

    Raises:
        ValueError: if ``client`` is ``None``.
    """
    if client is None:
        raise ValueError("client_visit_summary needs a client")
    now = now or timezone.now()

    appointments = Appointment.objects.filter(client=client).exclude(
        status=Appointment.Status.CANCELLED
    )
    total_visits = appointments.count()

    last_visit = (
        appointments.filter(start__lt=now)
        .order_by("-start", "-pk")
        .values_list("start", flat=True)
        .first()
    )
    next_appointment = (
        appointments.filter(start__gte=now)
        .select_related("staff_member", "service", "service__category")
        .order_by("start", "pk")
        .first()
    )

    amount = SaleItem.objects.filter(
        sale__client=client
    ).exclude(sale__status=Sale.Status.VOIDED).aggregate(
        total=Sum(F("unit_price") * F("quantity"))
    )["total"]
    lifetime_spend = (
        Decimal(amount).quantize(_CENTS) if amount is not None else _ZERO
    )

    return ClientVisitSummary(
        client=client,
        total_visits=total_visits,
        last_visit=last_visit,
        next_appointment=next_appointment,
        lifetime_spend=lifetime_spend,
        record_note_count=ClientNote.objects.filter(client=client).count(),
        appointment_note_count=AppointmentNote.objects.filter(
            appointment__client=client
        ).count(),
    )


# Short alias, matching the module name.
client_summary = client_visit_summary
