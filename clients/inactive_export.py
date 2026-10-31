"""Inactive clients CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a client or appointment,
and never sends anything. This is a report export, not marketing:
there is deliberately no messaging, no opt-in handling, and no
provider code of any kind here.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.

One source of truth: the rows come from
:func:`clients.inactive.inactive_clients` called with exactly the
arguments given here (``salon``, ``days``, ``now`` and
``threshold_days`` are passed through unchanged) -- this module
does not re-implement the inactivity rule, the visit definition,
the threshold boundary, the ordering, or the salon scoping. The
CSV string is built from the dict list returned by
:func:`export_inactive_clients`, so the two formats can never
disagree.

Columns are only what ``inactive_clients`` actually exposes: the
client id (``client_id``), the client's name (``first_name`` /
``last_name``, via the row's ``client``), the last visit date
(``last_appointment_date``; empty when the client has never
visited), and ``days_since_last_visit`` (empty in the same case).
No contact details (no email, no phone) and no invented fields
are included.
"""
import csv
import io

from clients.inactive import DEFAULT_INACTIVE_DAYS, inactive_clients

__all__ = [
    "INACTIVE_FIELDNAMES",
    "export_inactive_clients",
    "export_inactive_csv",
    "export_inactive_clients_csv",
    "inactive_csv",
]

#: Column / key order shared by the dict export and the CSV export.
INACTIVE_FIELDNAMES = [
    "client_id",
    "first_name",
    "last_name",
    "last_appointment_date",
    "days_since_last_visit",
]


def _record(row):
    last_date = row.last_appointment_date
    return {
        "client_id": row.client_id,
        "first_name": row.client.first_name,
        "last_name": row.client.last_name,
        "last_appointment_date": (
            last_date.isoformat() if last_date is not None else None
        ),
        "days_since_last_visit": row.days_since_last_visit,
    }


def export_inactive_clients(salon=None, days=DEFAULT_INACTIVE_DAYS, *,
                            now=None, threshold_days=None):
    """Return inactive clients as a list of dicts.

    Arguments are exactly those of
    :func:`clients.inactive.inactive_clients` and are passed
    through to it unchanged: ``salon`` optionally scopes the
    report to one salon, ``days`` / ``threshold_days`` set the
    inactivity window, and ``now`` is the reference instant.
    Each entry is a dict with exactly :data:`INACTIVE_FIELDNAMES`
    keys, in the order ``inactive_clients`` returns its rows
    (never-visited first, then last visit oldest first, then
    client id). No inactive clients exports as ``[]``.
    """
    rows = inactive_clients(
        salon=salon, days=days, now=now, threshold_days=threshold_days
    )
    return [_record(row) for row in rows]


def export_inactive_csv(salon=None, days=DEFAULT_INACTIVE_DAYS, *,
                        now=None, threshold_days=None):
    """Return inactive clients as a CSV string.

    Arguments are the same as :func:`export_inactive_clients`
    (and therefore the same as ``inactive_clients``). The header
    row is :data:`INACTIVE_FIELDNAMES` and every data row comes
    from :func:`export_inactive_clients` with the same arguments,
    so the CSV and list exports always agree. No inactive clients
    exports as the header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=INACTIVE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_inactive_clients(
        salon=salon, days=days, now=now, threshold_days=threshold_days
    ):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_inactive_clients_csv = export_inactive_csv
inactive_csv = export_inactive_csv
