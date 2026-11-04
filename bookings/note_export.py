"""Appointment-note verbatim CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment or a note.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's appointment-only notes
as a plain, JSON-serializable list of dicts
(:func:`export_appointment_notes`) and as a CSV string
(:func:`export_appointment_notes_csv`) built from that same list,
so the two formats can never disagree -- one source of truth.

This is the non-search verbatim twin of
:mod:`bookings.note_search_export` and mirrors the shape of
:mod:`clients.note_export`: where that module exports persistent
client record notes, this one exports appointment-only notes --
the second of the two note kinds, which must never blur. Only
``AppointmentNote`` rows are queried; ``ClientNote`` rows never
appear here, and this module does not import or query clients
models beyond the salon scoping below.

Columns are only real fields, verbatim as stored: the note's
``appointment_id``, its ``id`` (``note_id``), its ``author_name``,
its ``body``, and its ``created_at`` (ISO-8601). No fields are
invented and no other appointment or client fields are included.

Salon isolation follows :mod:`bookings.note_search` and
:mod:`bookings.search`: an appointment belongs to a salon via
both its client and its staff member, so only notes whose
appointment matches both ``appointment__client__salon`` and
``appointment__staff_member__salon`` are included. ``None``
salon exports as ``[]`` / the header row alone.

Date range: optional, inclusive local dates filtered on the
note's ``created_at`` in the salon's timezone
(``bookings.availability._tz``, the :mod:`bookings.export` /
:mod:`bookings.breaks` convention) -- the window is [start of
``date_from``, start of the day after ``date_to``). Either bound
may be given alone and then defaults the other (a single-day
range); datetimes are reduced to their salon-local date. No
range returns every appointment note for the salon; a reversed
range exports as ``[]``.

Appointment filter: optional ``appointment`` (default ``None``)
restricts the export to that one appointment's notes. The date
window still applies on top of it. ``None`` is exactly the
previous salon-wide behaviour; an appointment from another
salon exports as ``[]`` because the salon scoping above never
matches its notes.

Ordering is deterministic: by ``appointment_id``, then the
note's ``created_at``, then the note's ``id``.
"""
import csv
import io
from datetime import datetime, time, timedelta

from bookings.availability import _tz
from bookings.models import AppointmentNote

__all__ = [
    "NOTE_FIELDNAMES",
    "APPOINTMENT_NOTE_FIELDNAMES",
    "note_record",
    "export_appointment_notes",
    "export_appointment_notes_csv",
    "export_notes",
    "export_notes_csv",
    "appointment_notes_csv",
    "notes_csv",
]

#: Column / key order shared by the dict export and the CSV export.
NOTE_FIELDNAMES = [
    "appointment_id",
    "note_id",
    "author_name",
    "body",
    "created_at",
]
APPOINTMENT_NOTE_FIELDNAMES = NOTE_FIELDNAMES


def _dt(value):
    return value.isoformat() if value is not None else None


def _as_local_date(value, tz):
    if isinstance(value, datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    return value


def note_record(note):
    return {
        "appointment_id": note.appointment_id,
        "note_id": note.pk,
        "author_name": note.author_name,
        "body": note.body,
        "created_at": _dt(note.created_at),
    }


#: Backwards-compatible private alias for the one record builder.
_record = note_record


def export_appointment_notes(salon, date_from=None, date_to=None,
                             appointment=None):
    """Return ``salon``'s appointment-only notes verbatim as dicts.

    Each entry is a dict with exactly :data:`NOTE_FIELDNAMES`
    keys, ordered by (``appointment_id``, note ``created_at``,
    note ``id``). ``date_from`` / ``date_to`` are optional
    inclusive local dates on the note's ``created_at`` (see the
    module docstring). ``appointment`` optionally restricts the
    export to that one appointment's notes (default ``None`` =
    every appointment in the salon, the previous behaviour);
    the date window still applies when both are given. A salon
    with no appointment notes in range exports as ``[]``.
    """
    if salon is None:
        return []
    notes = (
        AppointmentNote.objects.filter(
            appointment__client__salon=salon,
            appointment__staff_member__salon=salon,
        )
        .select_related("appointment")
        .order_by("appointment_id", "created_at", "id")
    )
    if appointment is not None:
        notes = notes.filter(appointment=appointment)
    if date_from is not None or date_to is not None:
        tz = _tz(salon)
        first = _as_local_date(
            date_from if date_from is not None else date_to, tz)
        last = _as_local_date(
            date_to if date_to is not None else date_from, tz)
        if last < first:
            return []
        window_start = datetime.combine(first, time.min, tzinfo=tz)
        window_end = datetime.combine(
            last + timedelta(days=1), time.min, tzinfo=tz)
        notes = notes.filter(
            created_at__gte=window_start, created_at__lt=window_end)
    return [_record(note) for note in notes]


def export_appointment_notes_csv(salon, date_from=None, date_to=None,
                                 appointment=None):
    """Return ``salon``'s appointment notes as a CSV string.

    The header row is :data:`NOTE_FIELDNAMES` and every data row
    comes from :func:`export_appointment_notes` with the same
    arguments, so the CSV and list exports always agree. A salon
    with no appointment notes in range exports as the header row
    alone. Lines end ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NOTE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_appointment_notes(
            salon, date_from, date_to, appointment=appointment):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_notes = export_appointment_notes
export_notes_csv = export_appointment_notes_csv
appointment_notes_csv = export_appointment_notes_csv
notes_csv = export_appointment_notes_csv
