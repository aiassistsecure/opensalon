"""Salon-scoped search over persistent client record notes.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a client or a note.

Searches :class:`clients.models.ClientNote` only: persistent
record notes that live on the client profile across visits.
Appointment-only notes live in the bookings app
(``bookings.AppointmentNote``) and must NEVER appear here -- the
two note kinds never blur. This module therefore queries
``ClientNote`` only; it does not import or query the bookings
models.

One source of truth: the note text is ``ClientNote.body`` and the
owning client is ``ClientNote.client``; nothing is copied or
invented. Salon isolation: only notes whose client belongs to the
given salon (``client__salon``) can ever be returned.
"""
from clients.models import ClientNote

__all__ = ["search_client_notes"]


def search_client_notes(salon, query):
    """Return ``salon``'s client record notes matching ``query``.

    Args:
        salon: the ``saloncore.Salon`` to search within.
        query: search text; matched case-insensitively as a
            substring against the note ``body``. An empty,
            whitespace-only, or ``None`` query returns all of the
            salon's record notes.

    Returns:
        A queryset of ``ClientNote`` (with ``client`` prefetched
        via ``select_related``, so each result carries its note
        and its client), ordered newest first: ``-created_at``
        with ``-id`` as a deterministic tie-break for notes sharing
        a timestamp. Appointment-only notes are never included,
        whatever their text.
    """
    notes = ClientNote.objects.filter(
        client__salon=salon
    ).select_related("client")
    text = (query or "").strip()
    if text:
        notes = notes.filter(body__icontains=text)
    return notes.order_by("-created_at", "-id")
