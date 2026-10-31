"""Client record-note CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a client or a note.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's persistent client
record notes as a plain, JSON-serializable list of dicts
(:func:`export_notes`) and as a CSV string
(:func:`export_notes_csv`) built from that same list, so the two
formats can never disagree -- one source of truth.

Kind separation: only persistent client record notes are exported
(``ClientNote``). Appointment-only notes live in the bookings app
(``AppointmentNote``) and must never appear here -- the two note
kinds never blur. This module therefore queries ``ClientNote``
only; it does not import or query the bookings models.

Columns are only real fields: the client's ``external_id`` and
name (``first_name`` / ``last_name``), the note's ``id``, its
``created_at``, and its text (``body``). No other client fields
are included -- in particular no contact details beyond the name
(no email, no phone) -- and no fields are invented.

Ordering is deterministic: by client (``last_name``, then
``first_name``, then client ``id``, matching ``Client``'s model
ordering tightened with the ``id`` tie-break), then the note's
``created_at``, then the note's ``id``.

Salon isolation: only notes whose client belongs to the given
salon (``client__salon``) are included.
"""
import csv
import io

from clients.models import ClientNote

__all__ = [
    "NOTE_FIELDNAMES",
    "export_notes",
    "export_notes_csv",
    "notes_csv",
]

#: Column / key order shared by the dict export and the CSV export.
NOTE_FIELDNAMES = [
    "client_external_id",
    "client_first_name",
    "client_last_name",
    "note_id",
    "created_at",
    "body",
]


def _dt(value):
    return value.isoformat() if value is not None else None


def _record(note):
    client = note.client
    return {
        "client_external_id": client.external_id,
        "client_first_name": client.first_name,
        "client_last_name": client.last_name,
        "note_id": note.pk,
        "created_at": _dt(note.created_at),
        "body": note.body,
    }


def export_notes(salon):
    """Return ``salon``'s persistent client record notes as dicts.

    Each entry is a dict with exactly :data:`NOTE_FIELDNAMES`
    keys. Only notes on clients of ``salon`` are included, ordered
    by (client ``last_name``, client ``first_name``, client
    ``id``, note ``created_at``, note ``id``). A salon with no
    record notes exports as ``[]``.
    """
    notes = (
        ClientNote.objects.filter(client__salon=salon)
        .select_related("client")
        .order_by(
            "client__last_name",
            "client__first_name",
            "client__id",
            "created_at",
            "id",
        )
    )
    return [_record(note) for note in notes]


def export_notes_csv(salon):
    """Return ``salon``'s record notes as a CSV string.

    The header row is :data:`NOTE_FIELDNAMES` and every data row
    comes from :func:`export_notes` with the same argument, so
    the CSV and list exports always agree. A salon with no record
    notes exports as the header row alone. Lines end ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NOTE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_notes(salon):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
notes_csv = export_notes_csv
