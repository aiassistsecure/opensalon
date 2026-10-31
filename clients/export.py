"""Single-client export service.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports ONE client in full as a plain,
JSON-serializable dict -- the per-client counterpart of saloncore's
``export_salon_data`` command, following the same conventions
(plain dicts, datetimes as ISO-8601 strings).

Opt-ins exactly as stored: ``Client`` carries a single flag per
channel -- ``sms_opt_in`` and ``email_opt_in`` -- and each flag
gates both marketing and appointment reminders on that channel
(see ``clients.optins``). This export therefore reports exactly
those two stored flags; it does not invent separate
marketing/reminder flags.

Notes: only persistent client record notes (``ClientNote``) are
included. Appointment-only notes live in the bookings app and are
never included here -- the two note kinds never blur.

Backend only: no views, templates, or UI.
"""
from clients.models import ClientNote

__all__ = ["export_client"]


def _dt(value):
    return value.isoformat() if value is not None else None


def export_client(client):
    """Return ``client``'s full record as a JSON-serializable dict.

    Includes the core fields, ``external_id``, the opt-in states
    exactly as stored (``sms_opt_in`` / ``email_opt_in``), and the
    client's persistent record notes in chronological order
    (oldest first). A client with no notes exports ``"notes": []``.
    All datetimes are ISO-8601 strings.
    """
    if client.pk is None:
        notes = ClientNote.objects.none()
    else:
        notes = client.notes.order_by("created_at", "id")
    return {
        "id": client.id,
        "salon_id": client.salon_id,
        "external_id": client.external_id,
        "first_name": client.first_name,
        "last_name": client.last_name,
        "email": client.email,
        "phone": client.phone,
        "sms_opt_in": client.sms_opt_in,
        "email_opt_in": client.email_opt_in,
        "active": client.active,
        "created_at": _dt(client.created_at),
        "notes": [
            {
                "id": note.id,
                "client_id": note.client_id,
                "body": note.body,
                "author_name": note.author_name,
                "created_at": _dt(note.created_at),
            }
            for note in notes
        ],
    }
