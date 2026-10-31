"""Client's upcoming online bookings as display-ready rows (read-only).

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
"my upcoming bookings" view in online booking acts on (see
:mod:`onlinebooking.services` for the reschedule/cancel paths).
If a channel flag is ever added to ``Appointment``, this is the
one place that should start filtering on it.

What counts as upcoming
-----------------------
* ``start >= now`` (``now`` defaults to
  ``django.utils.timezone.now()``; an appointment starting exactly
  at ``now`` counts as upcoming — the same boundary rule as
  :mod:`bookings.client_history` and :mod:`onlinebooking.lookup`).
* Non-cancelled: only ``Appointment.Status.CANCELLED`` is
  excluded. A cancelled booking's slot is freed and it is no
  longer a booking; every other status is carried through on the
  row's appointment so callers can style or filter further.
* Salon-scoped on client and staff member, and — when the
  appointment has a service — on the service's category. An
  appointment whose service is ``None`` is NOT excluded by the
  salon scope: its display name comes from the appointment's
  ``service_name`` snapshot (see below).
* Ordered soonest first: ``start``, with ``pk`` as a
  deterministic tie-break — the order the visits will happen.

Rows, not appointments
----------------------
Unlike :mod:`onlinebooking.lookup` (which returns an
``Appointment`` queryset), each result here is an
:class:`UpcomingBooking` row exposing exactly what a list view
needs without per-row queries (staff and service are
``select_related``-loaded):

* ``appointment`` — the ``bookings.Appointment`` instance.
* ``staff_display_name`` — ``staff_member.display_name``.
* ``service_name`` — ``service.name`` when the appointment has a
  service, otherwise the appointment's verbatim ``service_name``
  snapshot (``""`` when neither exists, never a crash).
* ``start`` / ``end`` — the appointment's aware datetimes.
"""
from dataclasses import dataclass
from datetime import datetime

from django.db.models import Q
from django.utils import timezone

from bookings.models import Appointment

__all__ = ["UpcomingBooking", "upcoming_bookings"]


@dataclass(frozen=True)
class UpcomingBooking:
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


def _service_name(appointment):
    if appointment.service is not None:
        return appointment.service.name
    return appointment.service_name or ""


def upcoming_bookings(salon, client, now=None):
    """Return ``client``'s upcoming non-cancelled bookings in ``salon``.

    Args:
        salon: a ``saloncore.Salon`` instance the result is
            scoped to.
        client: a ``clients.Client`` instance.
        now: reference instant for "upcoming"; defaults to
            ``django.utils.timezone.now()``. Pass an aware
            datetime in tests for a deterministic boundary.

    Returns:
        A list of :class:`UpcomingBooking`, ordered by start
        (then appointment pk). Empty when ``salon`` or ``client``
        is ``None``, when the client belongs to a different
        salon, or when nothing qualifies. See the module
        docstring for the online-booking origin limitation.
    """
    if salon is None or client is None:
        return []
    now = now or timezone.now()
    appointments = (
        Appointment.objects.filter(
            client=client,
            client__salon=salon,
            staff_member__salon=salon,
            start__gte=now,
        )
        .filter(Q(service__isnull=True) | Q(service__category__salon=salon))
        .exclude(status=Appointment.Status.CANCELLED)
        .select_related("staff_member", "service")
        .order_by("start", "pk")
    )
    return [
        UpcomingBooking(
            appointment=appt,
            staff_display_name=appt.staff_member.display_name,
            service_name=_service_name(appt),
            start=appt.start,
            end=appt.end,
        )
        for appt in appointments
    ]
