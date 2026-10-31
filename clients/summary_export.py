"""Client summary CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a client, appointment,
sale, or note, and never sends anything.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.

One source of truth: every row comes from
:func:`clients.summary.client_visit_summary` called once per
client with exactly the arguments given here (the client and
``now`` are passed through unchanged) -- this module does not
re-implement the visit count, the last/next appointment rule,
the lifetime-spend derivation, or the note counts. The CSV
string is built from the dict list returned by
:func:`export_client_summaries`, so the two formats can never
disagree. The only salon scoping done here is listing ``salon``'s
clients: ``client_visit_summary`` itself is per-client (it has
no salon argument and isolates by client), so a client from
another salon is never listed and never summarised.

Columns are only what ``client_visit_summary`` actually returns:
the client id (``client_id``), the client's name (``first_name``
/ ``last_name``, via the summary's ``client``), ``total_visits``,
``last_visit``, ``next_appointment_start`` (the start of the
summary's ``next_appointment``), ``lifetime_spend`` (as a string
to two decimal places, so the dict form stays JSON-serializable),
and the two note counts. No contact details (no email, no phone)
and no invented fields are included.

Two kinds of notes, never blurred: the summary's
``record_note_count`` (persistent client record notes) and
``appointment_note_count`` (notes on one appointment only) are
exported as separate columns exactly as the summary returns
them, with no combined note total. No note body or text from
either kind ever appears -- only the summary's counts.
"""
import csv
import io
from decimal import Decimal

from clients.models import Client
from clients.summary import client_visit_summary

__all__ = [
    "SUMMARY_FIELDNAMES",
    "export_client_summaries",
    "export_client_summaries_csv",
    "export_client_summary_csv",
    "export_summary_csv",
    "summary_csv",
]

#: Column / key order shared by the dict export and the CSV export.
SUMMARY_FIELDNAMES = [
    "client_id",
    "first_name",
    "last_name",
    "total_visits",
    "last_visit",
    "next_appointment_start",
    "lifetime_spend",
    "record_note_count",
    "appointment_note_count",
]

_CENTS = Decimal("0.01")


def _dt(value):
    return value.isoformat() if value is not None else None


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _record(summary):
    return {
        "client_id": summary.client_id,
        "first_name": summary.client.first_name,
        "last_name": summary.client.last_name,
        "total_visits": summary.total_visits,
        "last_visit": _dt(summary.last_visit),
        "next_appointment_start": _dt(summary.next_appointment_start),
        "lifetime_spend": _money(summary.lifetime_spend),
        "record_note_count": summary.record_note_count,
        "appointment_note_count": summary.appointment_note_count,
    }


def export_client_summaries(salon, now=None):
    """Return ``salon``'s client summaries as a list of dicts.

    ``salon`` scopes the export to one salon's clients (required);
    ``now`` is passed through unchanged to
    :func:`clients.summary.client_visit_summary` for every client.
    Each entry is a dict with exactly :data:`SUMMARY_FIELDNAMES`
    keys, ordered by (``last_name``, ``first_name``, ``id``),
    matching ``Client``'s model ordering tightened with the
    ``id`` tie-break used by sibling exports. A salon with no
    clients exports as ``[]``.
    """
    clients = Client.objects.filter(salon=salon).order_by(
        "last_name", "first_name", "id"
    )
    return [
        _record(client_visit_summary(client, now=now))
        for client in clients
    ]


def export_client_summaries_csv(salon, now=None):
    """Return ``salon``'s client summaries as a CSV string.

    Arguments are the same as :func:`export_client_summaries`
    (and therefore the same ``now`` as ``client_visit_summary``).
    The header row is :data:`SUMMARY_FIELDNAMES` and every data
    row comes from :func:`export_client_summaries` with the same
    arguments, so the CSV and list exports always agree. A salon
    with no clients exports as the header row alone. Lines end
    with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=SUMMARY_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_client_summaries(salon, now=now):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_client_summary_csv = export_client_summaries_csv
export_summary_csv = export_client_summaries_csv
summary_csv = export_client_summaries_csv
