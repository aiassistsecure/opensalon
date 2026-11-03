"""Salon-scoped search over appointment-only notes.

Backend only -- no views, templates, or UI. Read-only.

Searches :class:`bookings.models.AppointmentNote` only:
appointment-only notes attached to one appointment. Persistent
client record notes live in the clients app (``ClientNote``) and
must NEVER appear here -- the two note kinds never blur. This
module therefore queries ``AppointmentNote`` only.

Salon isolation: an appointment belongs to a salon via both its
client and its staff member (as in :mod:`bookings.search`), so
only notes whose appointment matches both
``appointment__client__salon`` and
``appointment__staff_member__salon`` can ever be returned.
"""
from django.db.models import Q

from bookings.models import AppointmentNote

__all__ = ["search_appointment_notes"]


def search_appointment_notes(salon, query=None):
    """Return ``salon``'s appointment notes matching ``query``.

    ``query`` is matched case-insensitively as a substring against
    the note ``body`` and ``author_name``. An empty,
    whitespace-only, or ``None`` query returns all of the salon's
    appointment notes. Results are ordered newest first:
    ``-created_at`` with ``-id`` as a deterministic tie-break,
    with ``appointment`` (and its client) prefetched.
    """
    if salon is None:
        return AppointmentNote.objects.none()
    notes = AppointmentNote.objects.filter(
        appointment__client__salon=salon,
        appointment__staff_member__salon=salon,
    ).select_related("appointment", "appointment__client",
                     "appointment__staff_member")
    text = (query or "").strip() if not isinstance(query, str) \
        else query.strip()
    if text:
        notes = notes.filter(
            Q(body__icontains=text) | Q(author_name__icontains=text)
        )
    return notes.order_by("-created_at", "-id")
