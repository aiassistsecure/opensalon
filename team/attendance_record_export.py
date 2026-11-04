"""Attendance record CSV export service for the team app.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an attendance record
or a staff member.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

One source of truth: every row is a stored
:class:`team.models.AttendanceRecord` row, verbatim -- this
module does not pair check-in / check-out sessions, derive a
member's current state, recompute durations, or compute
anything new. A check-in exports its stored ``event_type``,
``recorded_at`` and ``note``, exactly as stored. Session
pairing and summaries stay in
:mod:`team.attendance_summary` / :mod:`team.attendance_export`
and are not this export's business.

Scoping: a salon's records are the rows whose staff member
belongs to that salon (``staff_member__salon``), in the
model's own ordering (``-recorded_at``, ``-id``).

Per-staff-member filter: both export functions accept an
optional ``staff_member`` (default ``None``). With ``None``
the output is the salon-wide export, unchanged. With a staff
member, only that member's records are included; the salon
filter still applies, so a staff member from another salon
exports as empty.

Columns are only fields the row and its stored relation
actually carry: ``id``, ``salon_id`` (the staff member's
salon), ``staff_member_id`` / ``staff_name`` (the member's
``display_name``), ``event_type`` (as stored),
``recorded_at`` (ISO-8601, as stored), and ``note`` (as
stored, empty when the row stores none).

Deliberately excluded: the staff member's ``pin`` (a
credential) and ``email`` (contact detail), as in the other
team exports. No rows exports as ``[]`` / the header row
alone. Lines end with ``"\\n"``.
"""
import csv
import io

from team.models import AttendanceRecord

__all__ = [
    "ATTENDANCE_RECORD_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_attendance_records",
    "export_attendance_records_csv",
    "attendance_records_csv",
]

#: Column / key order shared by the dict export and the CSV export.
ATTENDANCE_RECORD_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "staff_member_id",
    "staff_name",
    "event_type",
    "recorded_at",
    "note",
]
EXPORT_FIELDNAMES = ATTENDANCE_RECORD_EXPORT_FIELDNAMES


def _record(row):
    return {
        "id": row.pk,
        "salon_id": row.staff_member.salon_id,
        "staff_member_id": row.staff_member_id,
        "staff_name": row.staff_member.display_name,
        "event_type": row.event_type,
        "recorded_at": (
            row.recorded_at.isoformat() if row.recorded_at else None
        ),
        "note": row.note,
    }


def export_attendance_records(salon, staff_member=None):
    """Return ``salon``'s attendance records as a list of dicts.

    Each entry is one stored :class:`team.models.AttendanceRecord`
    row of the salon, as a dict with exactly
    :data:`ATTENDANCE_RECORD_EXPORT_FIELDNAMES` keys, in the
    model's ordering (``-recorded_at``, ``-id``). Read-only.

    ``staff_member`` is optional: the default ``None`` is the
    salon-wide export, unchanged. When a staff member is given,
    only that member's records are included; a staff member
    belonging to another salon exports as ``[]`` because the
    salon filter still applies.
    """
    rows = (
        AttendanceRecord.objects.filter(staff_member__salon=salon)
        .select_related("staff_member")
    )
    if staff_member is not None:
        rows = rows.filter(staff_member=staff_member)
    return [_record(row) for row in rows]


def export_attendance_records_csv(salon, staff_member=None):
    """Return ``salon``'s attendance records as a CSV string.

    The header row is :data:`ATTENDANCE_RECORD_EXPORT_FIELDNAMES`
    and every data row is rendered from
    :func:`export_attendance_records` with the same arguments, so
    the CSV and the dict export can never disagree. Lines end
    with ``"\\n"``. Read-only.

    ``staff_member`` is optional and passed through to
    :func:`export_attendance_records`: the default ``None`` is
    the salon-wide export, unchanged; a given staff member
    exports only that member's records (header alone when that
    member has none, or belongs to another salon).
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ATTENDANCE_RECORD_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_attendance_records(
            salon, staff_member=staff_member):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
attendance_records_csv = export_attendance_records_csv
