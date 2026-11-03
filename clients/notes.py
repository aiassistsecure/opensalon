"""Client record-notes service.

Pure service module -- no views, no UI. This is the single write/
read path for persistent client record notes
(``clients.ClientNote``).

Two kinds of notes exist in OpenSalon and they never blur:

- Client record notes (this module): persistent on the client
  profile across visits.
- Appointment notes (``bookings.AppointmentNote``): attached to
  one appointment only; they do not persist on the client
  profile.

This module only ever creates and queries ``ClientNote`` rows.
It never creates, copies to, or reads ``AppointmentNote``, and
nothing here writes a client record note onto an appointment.
"""
from django.core.exceptions import ValidationError

from clients.models import Client, ClientNote
from saloncore.models import Salon

__all__ = ["add_client_note", "list_client_notes",
           "validate_add_client_note"]


def _clean_body(body):
    """Return ``body`` stripped, or raise ``ValidationError``.

    This cleaning/validation is the single source of truth for
    what a record note's body may be: a non-empty string.
    """
    if not isinstance(body, str) or not body.strip():
        raise ValidationError({"body": "Note body must not be empty."})
    return body.strip()


def _resolve(salon, client):
    if not isinstance(salon, Salon) or salon.pk is None:
        raise ValidationError("salon must be a saved Salon instance.")
    if not isinstance(client, Client) or client.pk is None:
        raise ValidationError("client must be a saved Client instance.")
    if client.salon_id != salon.pk:
        raise ValidationError("Client belongs to a different salon.")


def validate_add_client_note(salon, client, body, author=""):
    """Validate an ``add_client_note`` call without writing.

    Performs every check :func:`add_client_note` performs and
    returns the normalized ``(body, author_name)`` the writer
    would store (both stripped; author blank by default).
    Raises the same ``ValidationError`` the writer would
    raise. Reads/writes nothing beyond validation reads, so
    it is safe for ``--dry-run`` previews on every backend
    (including NEDB, where a rolled-back transaction does
    not undo writes).
    """
    _resolve(salon, client)
    author_name = author.strip() if isinstance(author, str) else ""
    return _clean_body(body), author_name


def add_client_note(salon, client, body, author=""):
    """Add a persistent record note to ``client`` in ``salon``.

    ``body`` is cleaned (stripped) and validated here -- a note
    with no content is not a note -- and ``author`` becomes the
    note's author name (stripped, blank by default). Returns the
    created note. Raises ``ValidationError`` for an unsaved or
    mismatched salon/client or an empty body. The note lives on
    the client profile alone; no ``AppointmentNote`` is created.
    """
    body_clean, author_name = validate_add_client_note(
        salon, client, body, author=author)
    return ClientNote.objects.create(
        client=client, body=body_clean, author_name=author_name,
    )


def list_client_notes(salon, client):
    """Return ``client``'s record notes in ``salon``, newest first.

    Only notes attached to this exact client in this salon are
    returned -- never another client's notes and never the
    client's appointment-only notes.
    """
    _resolve(salon, client)
    return ClientNote.objects.filter(
        client=client, client__salon=salon,
    ).order_by("-created_at", "-pk")
