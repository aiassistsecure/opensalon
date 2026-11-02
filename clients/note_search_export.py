"""Client record-note search CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a client or a note.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export.

One source of truth: every row comes from
:func:`clients.note_search.search_client_notes` called with
exactly the arguments given here (``salon`` and ``query`` are
passed through unchanged) -- this module does not re-implement
the matching rule, the case-insensitive substring logic, the
salon scoping, or the ordering. The CSV string is built from the
dict list returned by :func:`export_note_search_results`, so the
two formats can never disagree.

Kind separation: only persistent client record notes are exported
(``ClientNote``, via the search service). Appointment-only notes
live in the bookings app (``AppointmentNote``) and must never
appear here -- the two note kinds never blur.

Columns mirror :mod:`clients.note_export` exactly: the client's
``external_id`` and name (``first_name`` / ``last_name``), the
note's ``id``, its ``created_at``, and its text (``body``). No
other client fields are included -- in particular no contact
details beyond the name (no email, no phone) -- and no fields
are invented.

Ordering is the search service's own: newest first
(``-created_at``, ``-id`` tie-break), unlike the unfiltered
:mod:`clients.note_export`, which orders by client.
"""
import csv
import io

from clients.note_search import search_client_notes

__all__ = [
    "NOTE_SEARCH_FIELDNAMES",
    "export_note_search_results",
    "export_note_search",
    "export_note_search_results_csv",
    "export_note_search_csv",
    "note_search_csv",
]

#: Column / key order shared by the dict and CSV exports; identical
#: to ``clients.note_export.NOTE_FIELDNAMES``.
NOTE_SEARCH_FIELDNAMES = [
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


def export_note_search_results(salon, query=None):
    """Return ``salon``'s record notes matching ``query`` as dicts.

    Arguments are exactly those of
    :func:`clients.note_search.search_client_notes` and are passed
    through to it unchanged: ``salon`` scopes the search to one
    salon (required) and ``query`` is the search text matched
    case-insensitively against the note ``body`` (an empty,
    whitespace-only, or ``None`` query returns all of the salon's
    record notes). Each entry is a dict with exactly
    :data:`NOTE_SEARCH_FIELDNAMES` keys, in the service's order
    (newest first). No matches exports as ``[]``.
    """
    return [_record(note) for note in search_client_notes(salon, query)]


def export_note_search_results_csv(salon, query=None):
    """Return ``salon``'s record notes matching ``query`` as CSV.

    Arguments are the same as :func:`export_note_search_results`
    (and therefore the same as ``search_client_notes``). The
    header row is :data:`NOTE_SEARCH_FIELDNAMES` and every data
    row comes from :func:`export_note_search_results` with the
    same arguments, so the CSV and list exports always agree.
    No matches exports as the header row alone. Lines end
    ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NOTE_SEARCH_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_note_search_results(salon, query):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_note_search = export_note_search_results
export_note_search_csv = export_note_search_results_csv
note_search_csv = export_note_search_results_csv
