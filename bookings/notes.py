"""Appointment-notes service.

Pure service module — no views, no UI. This is the single write/
read path for appointment-only notes (``bookings.AppointmentNote``).

Two kinds of notes exist in OpenSalon and they never blur:

- Appointment notes (this module): attached to one appointment
  only; they do not persist on the client profile across visits.
- Client record notes (``clients.ClientNote``): persistent on the
  client profile across visits.

This module only ever creates and queries ``AppointmentNote``
rows. It never creates, copies to, or reads ``ClientNote``, and
nothing here writes an appointment note onto the client record.
"""
from django.core.exceptions import ValidationError

from bookings.models import AppointmentNote


def add_note(appointment, text, author=""):
    """Add an appointment-only note to ``appointment``.

    ``text`` becomes the note's body and ``author`` its author
    name (both stored on ``AppointmentNote``). Returns the created
    note. Raises ``ValidationError`` for empty text — a note with
    no content is not a note. The note lives on this appointment
    alone; no ``ClientNote`` is created for the appointment's
    client.
    """
    if not text or not text.strip():
        raise ValidationError({"text": "Note text must not be empty."})
    return AppointmentNote.objects.create(
        appointment=appointment, body=text, author_name=author,
    )


def list_notes(appointment):
    """Return ``appointment``'s appointment-only notes, newest first.

    Only notes attached to this exact appointment are returned —
    never another appointment's notes (even for the same client)
    and never the client's persistent record notes.
    """
    return AppointmentNote.objects.filter(
        appointment=appointment,
    ).order_by("-created_at", "-pk")
