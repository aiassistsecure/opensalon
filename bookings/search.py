"""Appointment search service.

Pure service module — no views, no templates, no UI. This is the
read path for finding appointments in one salon by client name,
date range, staff member, and/or status.

Scoping: every query is scoped to the given salon via both the
client and the staff member (``client__salon`` and
``staff_member__salon``), so a search can never return another
salon's appointments. It deliberately does *not* scope via the
service: an appointment may have ``service=None`` with only its
``service_name`` snapshot (e.g. an imported service absent from
the price book), and such appointments are still this salon's
appointments and must be found — filtering or joining through
``service__category__salon`` would silently drop them, and
dereferencing ``service`` would crash on them. Related client,
staff, and service are ``select_related``-loaded (a null service
is handled by the ORM; callers should fall back to
``service_name`` when ``service`` is None, as in
:mod:`bookings.daybook`).

Filters (all optional, combined with AND):

- ``query``: case-insensitive substring matched against the
  client's first name, last name, and full ``"First Last"`` name.
  Empty, whitespace-only, or ``None`` means no name filter.
- ``date_from`` / ``date_to``: bounds on ``start``. A datetime is
  an exact bound (``start >= date_from`` / ``start <= date_to``);
  a plain ``date`` is a whole-day bound (``date_from`` is that
  day's start, ``date_to`` includes that whole day).
- ``staff_member``: a ``StaffMember`` instance or its pk.
- ``status``: an ``Appointment.Status`` value or its string.

Results are ordered by ``start``, with ``pk`` as a deterministic
tie-break. The returned queryset is lazily evaluated, so callers
may further filter or slice it.
"""
import datetime

from django.db.models import Q, Value
from django.db.models.functions import Concat

from bookings.models import Appointment

__all__ = ["search_appointments"]


def search_appointments(
    salon, query=None, date_from=None, date_to=None,
    staff_member=None, status=None,
):
    """Return ``salon``'s appointments matching the given filters.

    Args:
        salon: ``saloncore.Salon`` instance to scope to.
        query: optional client-name substring (case-insensitive).
        date_from: optional inclusive lower bound on ``start``
            (datetime, or date meaning that whole day's start).
        date_to: optional inclusive upper bound on ``start``
            (datetime, or date meaning that whole day).
        staff_member: optional ``StaffMember`` instance or pk.
        status: optional status value (e.g. ``"booked"`` or
            ``Appointment.Status.BOOKED``).

    Returns:
        A queryset of ``Appointment`` ordered by ``start``, ``pk``.
    """
    if salon is None:
        return Appointment.objects.none()
    appointments = (
        Appointment.objects.filter(
            client__salon=salon, staff_member__salon=salon,
        )
        .annotate(
            _client_full_name=Concat(
                "client__first_name", Value(" "), "client__last_name",
            )
        )
        .select_related("client", "staff_member", "service", "service__category")
    )
    text = "" if query is None else str(query).strip()
    if text:
        appointments = appointments.filter(
            Q(client__first_name__icontains=text)
            | Q(client__last_name__icontains=text)
            | Q(_client_full_name__icontains=text)
        )
    if date_from is not None:
        if isinstance(date_from, datetime.datetime):
            appointments = appointments.filter(start__gte=date_from)
        elif isinstance(date_from, datetime.date):
            appointments = appointments.filter(start__date__gte=date_from)
        else:
            appointments = appointments.filter(start__gte=date_from)
    if date_to is not None:
        if isinstance(date_to, datetime.datetime):
            appointments = appointments.filter(start__lte=date_to)
        elif isinstance(date_to, datetime.date):
            appointments = appointments.filter(start__date__lte=date_to)
        else:
            appointments = appointments.filter(start__lte=date_to)
    if staff_member is not None:
        staff_id = getattr(staff_member, "pk", staff_member)
        appointments = appointments.filter(staff_member_id=staff_id)
    if status is not None and str(status).strip() != "":
        appointments = appointments.filter(status=status)
    return appointments.order_by("start", "pk")
