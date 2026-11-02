"""New clients CSV export service.

Backend only — no views, templates, or UI. Read-only.
Founding rule (Exit Principle): anything a salon can enter, it can
fully export.

One source of truth: rows come from
:func:`clients.new_clients.new_clients` called with exactly the
arguments given here — this module does not re-implement the
first-visit rule, the window, or the ordering. The CSV string is
built from the dict list returned by :func:`export_new_clients`,
so the two formats can never disagree. Columns are only what
``new_clients`` exposes: ``client_id``, the client's name, and
the first visit (``first_appointment`` ISO datetime and
``first_appointment_date``). No contact details are included.
"""
import csv
import io

from clients.new_clients import new_clients

__all__ = [
    "NEW_CLIENTS_FIELDNAMES",
    "export_new_clients",
    "export_new_clients_csv",
    "export_new_client_csv",
    "new_clients_csv",
]

NEW_CLIENTS_FIELDNAMES = [
    "client_id",
    "first_name",
    "last_name",
    "first_appointment",
    "first_appointment_date",
]


def _record(row):
    first = row.first_appointment
    first_date = row.first_appointment_date
    return {
        "client_id": row.client_id,
        "first_name": row.client.first_name,
        "last_name": row.client.last_name,
        "first_appointment": first.isoformat() if first is not None else None,
        "first_appointment_date": (
            first_date.isoformat() if first_date is not None else None
        ),
    }


def export_new_clients(salon=None, start_date=None, end_date=None, **kwargs):
    """Return new clients in the window as a list of dicts.

    Arguments are exactly those of
    :func:`clients.new_clients.new_clients`, passed through
    unchanged. Each entry has exactly
    :data:`NEW_CLIENTS_FIELDNAMES` keys, in that function's order.
    No new clients exports as ``[]``.
    """
    rows = new_clients(salon, start_date, end_date, **kwargs)
    return [_record(row) for row in rows]


def export_new_clients_csv(salon=None, start_date=None, end_date=None, **kwargs):
    """Return new clients in the window as a CSV string.

    The header row is :data:`NEW_CLIENTS_FIELDNAMES` and every
    data row comes from :func:`export_new_clients` with the same
    arguments. No new clients exports as the header row alone.
    Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NEW_CLIENTS_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_new_clients(salon, start_date, end_date, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_new_client_csv = export_new_clients_csv
new_clients_csv = export_new_clients_csv
