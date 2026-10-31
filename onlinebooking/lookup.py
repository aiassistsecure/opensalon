"""Client lookup of upcoming online bookings (read-only).

Backend only — no views, templates, or branding. This is the read
path behind a client's "my upcoming bookings" view: the bookings
they can still act on through online booking (see
:mod:`onlinebooking.services` for the reschedule/cancel write
paths that operate on exactly these appointments).

Nothing new is stored and no booking logic is duplicated:

* A booking is a ``bookings.Appointment`` — online booking has no
  store of its own (see :mod:`onlinebooking.models`) and an
  appointment carries no channel flag, so this lookup returns the
  client's upcoming appointments in the salon regardless of the
  channel they were booked through. Inventing a channel split the
  model cannot support would be a second, false source of truth.
* Salon-scoped on every axis: the client, the staff member, and
  the service's category must all belong to the given salon.
  Querying with a salon the client does not belong to returns an
  empty result — never another salon's bookings, and no error
  that would confirm the client exists elsewhere.
* Future only: ``start >= now`` (``now`` defaults to
  ``django.utils.timezone.now()``; an appointment starting
  exactly at ``now`` counts as upcoming — the same boundary rule
  as :mod:`bookings.client_history`).
* Upcoming means still actionable online: only ``booked`` and
  ``confirmed`` appointments are returned — the statuses the
  online reschedule/cancel paths accept, and the remindable set
  in ``messaging``. Cancelled appointments are gone (their slot
  is freed), completed/no-show appointments are history, and
  arrived/in-service appointments are already underway; none of
  those is an upcoming booking.
* Ordered soonest first: ``start``, with ``pk`` as a
  deterministic tie-break for appointments sharing a start —
  the order the visits will happen.

Related staff, service, and service category are
``select_related``-loaded so rendering a list does not issue
per-appointment queries. The returned queryset is lazily
evaluated, so callers may further filter or slice it.
"""
from django.utils import timezone

from bookings.models import Appointment

__all__ = [
    "UPCOMING_BOOKING_STATUSES",
    "upcoming_online_bookings",
    "next_online_booking",
]

#: Statuses that are still an upcoming, online-actionable booking.
UPCOMING_BOOKING_STATUSES = (
    Appointment.Status.BOOKED,
    Appointment.Status.CONFIRMED,
)


def upcoming_online_bookings(salon, client, now=None):
    """Return ``client``'s upcoming bookings in ``salon``, soonest first.

    Args:
        salon: a ``saloncore.Salon`` instance the lookup is
            scoped to.
        client: a ``clients.Client`` instance.
        now: reference instant for "future"; defaults to
            ``django.utils.timezone.now()``. Pass an aware
            datetime in tests for a deterministic boundary.

    Returns:
        A queryset of ``Appointment`` — only booked/confirmed
        appointments of this client, in this salon, with
        ``start >= now``, ordered by ``start`` then ``pk``.
        Empty when the salon or client is ``None``, when the
        client belongs to a different salon, or when nothing
        qualifies.
    """
    if salon is None or client is None:
        return Appointment.objects.none()
    now = now or timezone.now()
    return (
        Appointment.objects.filter(
            client=client,
            client__salon=salon,
            staff_member__salon=salon,
            service__category__salon=salon,
            start__gte=now,
            status__in=UPCOMING_BOOKING_STATUSES,
        )
        .select_related("staff_member", "service", "service__category")
        .order_by("start", "pk")
    )


def next_online_booking(salon, client, now=None):
    """Return ``client``'s next upcoming booking in ``salon``, or None.

    The first appointment of :func:`upcoming_online_bookings`
    (soonest first), so ``None`` exactly when that lookup is
    empty.
    """
    return upcoming_online_bookings(salon, client, now=now).first()
