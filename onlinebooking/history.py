"""Client's past online bookings as display-ready rows (read-only).

Backend only — no views, templates, or branding.

Limitation — online-booking origin is NOT distinguishable
----------------------------------------------------------
An appointment carries no channel/origin flag, and online booking
stores nothing of its own (see :mod:`onlinebooking.models`): a
booking made online, by phone, or in person is the same
``bookings.Appointment`` row. Inventing a channel split the model
cannot support would be a second, false source of truth, so this
service does NOT claim to filter by origin. It is scoped to the
client's appointments at the given salon — the set a client's
"my past bookings" view in online booking acts on. If a channel
flag is ever added to ``Appointment``, this is the one place
that should start filtering on it.

What counts as past
-------------------
* ``start < now`` (``now`` defaults to
  ``django.utils.timezone.now()``; an appointment starting exactly
  at ``now`` counts as upcoming, not past — the same boundary rule
  as :mod:`bookings.client_history` and
  :mod:`onlinebooking.upcoming`).
* Cancelled bookings are INCLUDED, unlike upcoming: a cancelled
  past booking is part of the client's history. Each row flags
  it via ``is_cancelled`` (alias ``cancelled``) so callers can
  style or filter it without re-deriving the status check.
  Every other status is likewise carried through on the row's
  appointment.
* Salon-scoped on client and staff member, and — when the
  appointment has a service — on the service's category. An
  appointment whose service is ``None`` is NOT excluded by the
  salon scope: its display name comes from the appointment's
  ``service_name`` snapshot (see below).
* Ordered newest first: ``-start``, with ``-pk`` as a
  deterministic tie-break — history is read backwards, the most
  recent visit first.

Limit
-----
``limit`` caps how many rows are returned (default
:data:`DEFAULT_HISTORY_LIMIT`). Pass ``limit=None`` for the full
past history; a non-positive limit returns no rows.

Rows, not appointments
----------------------
Each result is a :class:`PastBooking` row exposing exactly what
a list view needs without per-row queries (staff and service are
``select_related``-loaded):

* ``appointment`` — the ``bookings.Appointment`` instance.
* ``staff_display_name`` — ``staff_member.display_name``.
* ``service_name`` — ``service.name`` when the appointment has a
  service, otherwise the appointment's verbatim ``service_name``
  snapshot (``""`` when neither exists, never a crash).
* ``start`` / ``end`` — the appointment's aware datetimes.
* ``is_cancelled`` — True when the appointment's status is
  ``Appointment.Status.CANCELLED``.
"""
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from bookings.models import Appointment

__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "PastBooking",
    "past_bookings",
    "booking_history",
]

#: Default maximum number of past bookings returned.
DEFAULT_HISTORY_LIMIT = 20


@dataclass(frozen=True)
class PastBooking:
    appointment: Appointment
    staff_display_name: str
    service_name: str
    start: datetime
    end: datetime

    @property
    def appointment_id(self):
        return self.appointment.pk

    @property
    def display_name(self):
        """Alias for :attr:`staff_display_name`."""
        return self.staff_display_name

    @property
    def staff_name(self):
        """Alias for :attr:`staff_display_name`."""
        return self.staff_display_name

    @property
    def is_cancelled(self):
        return self.appointment.status == Appointment.Status.CANCELLED

    @property
    def cancelled(self):
        """Alias for :attr:`is_cancelled`."""
        return self.is_cancelled


def _service_name(appointment):
    if appointment.service is not None:
        return appointment.service.name
    return appointment.service_name or ""


def past_bookings(salon, client, now=None, limit=DEFAULT_HISTORY_LIMIT):
    """Return ``client``'s past bookings in ``salon``, newest first.

    Args:
        salon: a ``saloncore.Salon`` instance the result is
            scoped to.
        client: a ``clients.Client`` instance.
        now: reference instant for "past"; defaults to
            ``django.utils.timezone.now()``. Pass an aware
            datetime in tests for a deterministic boundary.
        limit: maximum number of rows to return; defaults to
            :data:`DEFAULT_HISTORY_LIMIT`. ``None`` returns the
            full history; a non-positive value returns no rows.

    Returns:
        A list of :class:`PastBooking`, ordered by start
        descending (then appointment pk descending), including
        cancelled bookings flagged via ``is_cancelled``. Empty
        when ``salon`` or ``client`` is ``None``, when the client
        belongs to a different salon, or when nothing qualifies.
        See the module docstring for the online-booking origin
        limitation.
    """
    if salon is None or client is None:
        return []
    if limit is not None and limit <= 0:
        return []
    now = now or timezone.now()
    appointments = (
        Appointment.objects.filter(
            client=client,
            client__salon=salon,
            staff_member__salon=salon,
            start__lt=now,
        )
        .filter(Q(service__isnull=True) | Q(service__category__salon=salon))
        .select_related("staff_member", "service")
        .order_by("-start", "-pk")
    )
    if limit is not None:
        appointments = appointments[:limit]
    return [
        PastBooking(
            appointment=appt,
            staff_display_name=appt.staff_member.display_name,
            service_name=_service_name(appt),
            start=appt.start,
            end=appt.end,
        )
        for appt in appointments
    ]


#: Alias matching the module name.
booking_history = past_bookings
