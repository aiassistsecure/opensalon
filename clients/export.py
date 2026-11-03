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

Payload: when the client carries a verbatim source record in
``Client.payload`` (non-empty), it is included under ``payload``
so the source record round-trips through ``import_clients``
(which restores an export record's ``payload`` as-is). A client
with no payload exports exactly as before -- no ``payload`` key.

CSV: :func:`export_client_csv` renders the same record as a CSV
string (header plus one data row) built from :func:`export_client`
alone, so the two formats can never disagree -- one source of
truth. Nested values (``notes``, and ``payload`` when present)
are JSON-encoded into their cell so no field is dropped or
reshaped; a client with no ``payload`` exports an empty
``payload`` cell.

Backend only: no views, templates, or UI.
"""
import csv
import io
import json

from clients.models import ClientNote

__all__ = [
    "CLIENT_FIELDNAMES",
    "export_client",
    "export_client_csv",
]

#: Column / key order shared by the dict export and the CSV export:
#: exactly the ``export_client`` key order (with the optional
#: ``payload`` in its export position, after ``notes``).
CLIENT_FIELDNAMES = [
    "id",
    "salon_id",
    "external_id",
    "first_name",
    "last_name",
    "email",
    "phone",
    "sms_opt_in",
    "email_opt_in",
    "active",
    "created_at",
    "notes",
    "payload",
]


def _dt(value):
    return value.isoformat() if value is not None else None


def export_client(client):
    """Return ``client``'s full record as a JSON-serializable dict.

    Includes the core fields, ``external_id``, the opt-in states
    exactly as stored (``sms_opt_in`` / ``email_opt_in``), and the
    client's persistent record notes in chronological order
    (oldest first). A client with no notes exports ``"notes": []``.
    The verbatim ``payload`` is included only when present
    (non-empty). All datetimes are ISO-8601 strings.
    """
    if client.pk is None:
        notes = ClientNote.objects.none()
    else:
        notes = client.notes.order_by("created_at", "id")
    record = {
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
    payload = getattr(client, "payload", None)
    if payload:
        record["payload"] = payload
    return record


def export_client_csv(client):
    """Return ``client``'s full record as a CSV string.

    The header row is :data:`CLIENT_FIELDNAMES` and the single
    data row comes from :func:`export_client` with the same
    argument, so the CSV and dict exports always agree -- one
    source of truth. Nested values (``notes``, and ``payload``
    when present) are JSON-encoded into their cell so no field
    is dropped or reshaped; a client with no ``payload`` exports
    an empty ``payload`` cell. Lines end with ``"\\n"``.
    """
    record = export_client(client)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CLIENT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    row = {}
    for field in CLIENT_FIELDNAMES:
        value = record.get(field)
        if isinstance(value, (list, dict)):
            value = json.dumps(value)
        row[field] = value
    writer.writerow(row)
    return buffer.getvalue()
