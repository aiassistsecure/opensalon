"""Attendance summary CSV export service for the team app.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an attendance record
or a staff member, and nothing is sent.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

One source of truth: every figure comes verbatim from
:func:`team.attendance_summary.attendance_summary`, called
with exactly the arguments given here (``*args`` / ``**kwargs``
passed through unchanged) -- this module does not re-pair
check-in / check-out sessions, re-query attendance records,
recompute durations, or re-implement the salon scoping, the
salon-timezone day attribution, the zero-filling, or the
ordering of that service.

Rows are the two breakdowns the service's
:class:`~team.attendance_summary.AttendanceSummary` carries,
following the section pattern of sibling summary exports:

- ``section="staff"``: one row per ``per_staff`` entry
  (:class:`~team.attendance_summary.StaffAttendanceSummary`),
  in the service's order (display name, then id).
- ``section="day"``: one row per ``per_day`` entry
  (:class:`~team.attendance_summary.DayAttendanceSummary`),
  in the service's order (every day in range, zero-filled).

Columns are only fields those structures actually carry:
``salon_id`` (the result's ``salon_id``; empty for a
range-only call), ``start_date`` / ``end_date`` (ISO-8601,
inclusive), ``section``, ``staff_member_id`` /
``staff_name`` (staff rows only; from ``staff_member_id`` /
``display_name``), ``date`` (day rows only, ISO-8601),
``sessions_count``, ``closed_sessions``, ``open_sessions``,
``total_minutes`` (the entry's ``total_minutes``, derived by
the service from its ``total_duration``), and ``staff_count``
(day rows only). No invented fields are included.

An empty range is not header-only: the service zero-fills
active staff and every day in range, so the export carries
those zero rows. Lines end with ``"\\n"``.
"""
import csv
import io

from team.attendance_summary import attendance_summary

__all__ = [
    "ATTENDANCE_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_attendance_summary",
    "export_attendance_summary_csv",
    "attendance_summary_csv",
]

#: Column / key order shared by the dict export and the CSV export.
ATTENDANCE_EXPORT_FIELDNAMES = [
    "salon_id",
    "start_date",
    "end_date",
    "section",
    "staff_member_id",
    "staff_name",
    "date",
    "sessions_count",
    "closed_sessions",
    "open_sessions",
    "total_minutes",
    "staff_count",
]
EXPORT_FIELDNAMES = ATTENDANCE_EXPORT_FIELDNAMES


def _rows(result):
    base = {
        "salon_id": result.salon_id,
        "start_date": (
            result.start_date.isoformat() if result.start_date else None
        ),
        "end_date": (
            result.end_date.isoformat() if result.end_date else None
        ),
    }
    rows = []
    for entry in result.per_staff:
        rows.append({
            **base,
            "section": "staff",
            "staff_member_id": entry.staff_member_id,
            "staff_name": entry.display_name,
            "date": None,
            "sessions_count": entry.sessions_count,
            "closed_sessions": entry.closed_sessions,
            "open_sessions": entry.open_sessions,
            "total_minutes": entry.total_minutes,
            "staff_count": None,
        })
    for entry in result.per_day:
        rows.append({
            **base,
            "section": "day",
            "staff_member_id": None,
            "staff_name": None,
            "date": entry.day.isoformat() if entry.day else None,
            "sessions_count": entry.sessions_count,
            "closed_sessions": entry.closed_sessions,
            "open_sessions": entry.open_sessions,
            "total_minutes": entry.total_minutes,
            "staff_count": entry.staff_count,
        })
    return rows


def export_attendance_summary(*args, **kwargs):
    """Return the attendance summary as a list of dicts.

    Arguments are exactly those of
    :func:`team.attendance_summary.attendance_summary` and are
    passed through to it unchanged: call as
    ``export_attendance_summary(salon, start_date, end_date)``
    or ``export_attendance_summary(start_date, end_date)``,
    with the service's keyword aliases (``start=`` / ``end=``,
    ``date_from=`` / ``date_to=``) accepted as it accepts them.
    Each entry is a dict with exactly
    :data:`ATTENDANCE_EXPORT_FIELDNAMES` keys: staff rows
    first, then day rows, each in the service's order.
    Read-only.
    """
    return _rows(attendance_summary(*args, **kwargs))


def export_attendance_summary_csv(*args, **kwargs):
    """Return the attendance summary as a CSV string.

    Arguments are the same as :func:`export_attendance_summary`
    (and therefore the same as ``attendance_summary``), passed
    through unchanged. The header row is
    :data:`ATTENDANCE_EXPORT_FIELDNAMES` and every data row is
    rendered from the service result with the same arguments,
    so the CSV and the service can never disagree. Lines end
    with ``"\\n"``. Read-only.
    """
    result = attendance_summary(*args, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ATTENDANCE_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in _rows(result):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
attendance_summary_csv = export_attendance_summary_csv
