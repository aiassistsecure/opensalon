"""Bulk client export service.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports ALL clients as a plain,
JSON-serializable list -- the bulk counterpart of the single-client
export in ``clients.export`` -- and as a CSV string
(:func:`export_all_clients_csv`) built from that same list, so the
two formats can never disagree.

One source of truth: every record is serialized by
``clients.export.export_client`` and therefore carries exactly the
same field shape as the single-client export (core fields,
``external_id``, the opt-in flags exactly as stored -- ``sms_opt_in``
/ ``email_opt_in`` -- and the persistent record notes). This module
adds only one field per record: ``note_count``, the number of
persistent record notes (``len(record["notes"])``), annotated in the
queryset so callers can read a count without walking the notes list.

Ordering is deterministic: ``last_name``, then ``first_name``, then
``id`` as a tie-break for clients sharing both names (matching, and
tightening, ``Client``'s model ordering).

Notes: only persistent client record notes are counted / included.
Appointment data is never included here -- appointments (and
appointment-only notes) live in the bookings app, and the two note
kinds never blur.

Backend only: no views, templates, or UI.
"""
import csv
import io
import json

from django.db.models import Count

from clients.export import export_client
from clients.models import Client

__all__ = [
    "CLIENTS_FIELDNAMES",
    "export_all_clients",
    "export_all_clients_csv",
    "export_all",
    "export_clients",
    "export_all_csv",
    "export_clients_csv",
]

#: Column / key order shared by the dict export and the CSV export:
#: exactly the ``export_client`` key order (with the optional
#: ``payload`` in its export position), plus ``note_count`` last,
#: as appended by :func:`export_all_clients`.
CLIENTS_FIELDNAMES = [
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
    "note_count",
]


def export_all_clients(salon=None):
    """Return every client record as a list of JSON-serializable dicts.

    Args:
        salon: optional ``Salon`` instance; when given, only that
            salon's clients are exported. When omitted (default),
            ALL clients in the database are exported.

    Returns:
        A list, ordered by (``last_name``, ``first_name``, ``id``),
        of dicts in the ``export_client`` shape plus ``note_count``
        (int, >= 0). An empty client book exports as ``[]``.
    """
    clients = Client.objects.annotate(
        _record_note_count=Count("notes")
    )
    if salon is not None:
        clients = clients.filter(salon=salon)
    clients = clients.order_by("last_name", "first_name", "id")
    records = []
    for client in clients:
        record = export_client(client)
        record["note_count"] = client._record_note_count
        records.append(record)
    return records


def export_all_clients_csv(salon=None):
    """Return every client record as a CSV string.

    The header row is :data:`CLIENTS_FIELDNAMES` and every data
    row comes from :func:`export_all_clients` with the same
    argument, so the CSV and list exports always agree -- one
    source of truth. Nested values (``notes``, and ``payload``
    when present) are JSON-encoded into their cell so no field
    is dropped or reshaped; a client with no ``payload`` exports
    an empty ``payload`` cell. An empty client book exports as
    the header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CLIENTS_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_all_clients(salon=salon):
        row = {}
        for field in CLIENTS_FIELDNAMES:
            value = record.get(field)
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            row[field] = value
        writer.writerow(row)
    return buffer.getvalue()


# Aliases: the bulk counterpart is naturally reached for under any of
# these names; all point at the one implementation above.
export_all = export_all_clients
export_clients = export_all_clients
export_all_csv = export_all_clients_csv
export_clients_csv = export_all_clients_csv
