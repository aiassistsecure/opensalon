"""Bulk client export service.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports ALL clients as a plain,
JSON-serializable list -- the bulk counterpart of the single-client
export in ``clients.export``.

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
from django.db.models import Count

from clients.export import export_client
from clients.models import Client

__all__ = ["export_all_clients", "export_all", "export_clients"]


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


# Aliases: the bulk counterpart is naturally reached for under any of
# these names; all point at the one implementation above.
export_all = export_all_clients
export_clients = export_all_clients
