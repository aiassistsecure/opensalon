"""Appointment-note search CSV export service.

Backend only -- no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. Every row comes from
:func:`bookings.note_search.search_appointment_notes` called with
exactly the arguments given here -- this module does not
re-implement matching, salon scoping, or ordering. The CSV string
is built from the dict list, so the two formats can never disagree.

Kind separation: only appointment-only notes are exported
(``AppointmentNote``, via the search service). Persistent client
record notes (``ClientNote``) must never appear here.
"""
import csv
import io

from bookings.note_search import search_appointment_notes

__all__ = [
    "APPOINTMENT_NOTE_SEARCH_FIELDNAMES", "NOTE_SEARCH_FIELDNAMES",
    "export_appointment_note_search_results",
    "export_appointment_note_search_results_csv",
    "export_note_search_results", "export_note_search_results_csv",
    "export_appointment_note_search", "export_appointment_note_search_csv",
    "note_search_csv",
]

APPOINTMENT_NOTE_SEARCH_FIELDNAMES = [
    "appointment_id", "note_id", "created_at", "author_name", "body",
]
NOTE_SEARCH_FIELDNAMES = APPOINTMENT_NOTE_SEARCH_FIELDNAMES


def _dt(value):
    return value.isoformat() if value is not None else None


def _record(note):
    return {
        "appointment_id": note.appointment_id,
        "note_id": note.pk,
        "created_at": _dt(note.created_at),
        "author_name": note.author_name,
        "body": note.body,
    }


def export_appointment_note_search_results(salon, query=None):
    """Return ``salon``'s appointment notes matching ``query`` as dicts.

    Arguments are exactly those of ``search_appointment_notes`` and
    are passed through unchanged. Each entry has exactly
    :data:`APPOINTMENT_NOTE_SEARCH_FIELDNAMES` keys, newest first.
    No matches exports as ``[]``.
    """
    return [_record(n) for n in search_appointment_notes(salon, query)]


def export_appointment_note_search_results_csv(salon, query=None):
    """Return the same results as CSV (header alone if no matches)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=APPOINTMENT_NOTE_SEARCH_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()
    for record in export_appointment_note_search_results(salon, query):
        writer.writerow(record)
    return buffer.getvalue()


export_note_search_results = export_appointment_note_search_results
export_note_search_results_csv = export_appointment_note_search_results_csv
export_appointment_note_search = export_appointment_note_search_results
export_appointment_note_search_csv = (
    export_appointment_note_search_results_csv)
note_search_csv = export_appointment_note_search_results_csv
