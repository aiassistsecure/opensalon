"""Client appointment history service.

Pure service module — no views, no templates, no UI. This is the
read path for one client's appointment history, built only on the
existing ``bookings.Appointment`` model (one source of truth).

Ordering (documented, deliberate):

- Full history (``client_appointments`` with ``upcoming_only=False``,
  and ``past_appointments``) is newest first: ``-start``, with
  ``-pk`` as a deterministic tie-break for appointments sharing a
  start. History is read backwards — the most recent visit is the
  one a salon usually wants first.
- Upcoming appointments (``client_appointments`` with
  ``upcoming_only=True``, and ``upcoming_appointments``) are
  soonest first: ``start``, with ``pk`` as tie-break — the next
  visit comes first, in the order the visits will happen.

Past vs upcoming is split on ``start`` relative to ``now``:

- upcoming: ``start >= now``
- past: ``start < now``

An appointment starting exactly at ``now`` counts as upcoming.
This is a start-time rule, not a status rule: no status is filtered
out anywhere here. Cancelled, no-show, completed and in-progress
appointments are all part of a client's history; callers that need
to style or exclude a status can do so from the ``status`` value
carried on each returned appointment.

Isolation: every function filters on exactly the given client
(``client=client``) and nothing else, so a query can never return
another client's appointments — not even a client in the same
salon. Related staff, service and service category are
``select_related``-loaded so rendering a history list does not
issue per-appointment queries.
"""
from django.utils import timezone

from bookings.models import Appointment

__all__ = [
    "client_appointments",
    "past_appointments",
    "upcoming_appointments",
    "past_and_upcoming",
]


def _for_client(client):
    return Appointment.objects.filter(client=client).select_related(
        "staff_member", "service", "service__category"
    )


def client_appointments(client, upcoming_only=False, now=None):
    """Return ``client``'s appointments, and only that client's.

    Args:
        client: a ``clients.Client`` instance.
        upcoming_only: when False (default), return the full
            history ordered newest first (``-start``). When True,
            return only appointments with ``start >= now``,
            ordered soonest first (``start``).
        now: reference instant for ``upcoming_only``; defaults to
            ``django.utils.timezone.now()``. Pass an aware datetime
            in tests for a deterministic boundary.

    Returns:
        A queryset of ``Appointment`` — lazily evaluated, so
        callers may further filter or slice it.
    """
    qs = _for_client(client)
    if upcoming_only:
        now = now or timezone.now()
        return qs.filter(start__gte=now).order_by("start", "pk")
    return qs.order_by("-start", "-pk")


def upcoming_appointments(client, now=None):
    """Return ``client``'s upcoming appointments, soonest first.

    Upcoming means ``start >= now`` (``now`` defaults to
    ``timezone.now()``). Only this client's appointments.
    """
    now = now or timezone.now()
    return _for_client(client).filter(start__gte=now).order_by("start", "pk")


def past_appointments(client, now=None):
    """Return ``client``'s past appointments, newest first.

    Past means ``start < now`` (``now`` defaults to
    ``timezone.now()``). Only this client's appointments.
    """
    now = now or timezone.now()
    return _for_client(client).filter(start__lt=now).order_by("-start", "-pk")


def past_and_upcoming(client, now=None):
    """Split ``client``'s appointments into ``(past, upcoming)``.

    Both querysets use the same ``now`` (default
    ``timezone.now()``), the same boundary rule (exactly-now is
    upcoming) and the ordering documented in the module docstring,
    so every appointment of this client appears in exactly one of
    the two, and none of another client's appears in either.
    """
    now = now or timezone.now()
    return past_appointments(client, now=now), upcoming_appointments(
        client, now=now
    )
