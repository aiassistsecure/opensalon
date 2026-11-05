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

Event-type filter: both export functions also accept an
optional ``event_type`` (default ``None``). With ``None``
the output is unchanged. With a value, only records whose
stored ``event_type`` exactly matches it (the
``AttendanceRecord.EventType`` slugs ``check_in`` /
``check_out``) are included. It composes with the
staff-member filter and the date window (all AND).

Date window: both export functions also accept an optional
``start`` / ``end`` window pair (aliases ``start_date`` /
``end_date``), filtering on ``recorded_at``. Each bound may
be a ``date``, a ``datetime``, or ``None`` (the default,
unbounded -- with both ``None`` the output is unchanged).
The range is start-inclusive and end-exclusive after
normalisation: a ``date`` start means the start of that
day, and a ``date`` end means the start of the *following*
day, so passing two dates includes the whole end day. A
``datetime`` is used as given (naive datetimes are
interpreted in the current time zone). The window composes
with the staff-member filter (window AND record).

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
from datetime import date, datetime, time, timedelta

from django.utils import timezone

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


def _bound(value, *, is_end):
    """Normalise a range bound to an aware datetime or ``None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        bound = value
    elif isinstance(value, date):
        bound = datetime.combine(value, time.min)
        if is_end:
            bound += timedelta(days=1)
    else:
        raise ValueError("range bounds must be a date, datetime, or None")
    if timezone.is_naive(bound):
        bound = timezone.make_aware(bound, timezone.get_current_timezone())
    return bound


def _resolve_window(start, end, kwargs):
    """Fold the ``start_date`` / ``end_date`` aliases into start/end."""
    if "start_date" in kwargs:
        if start is not None:
            raise TypeError("multiple values for start")
        start = kwargs.pop("start_date")
    if "end_date" in kwargs:
        if end is not None:
            raise TypeError("multiple values for end")
        end = kwargs.pop("end_date")
    if "date_from" in kwargs:
        if start is not None:
            raise TypeError("multiple values for start")
        start = kwargs.pop("date_from")
    if "date_to" in kwargs:
        if end is not None:
            raise TypeError("multiple values for end")
        end = kwargs.pop("date_to")
    if kwargs:
        raise TypeError(
            f"unexpected arguments: {', '.join(sorted(kwargs))}")
    return start, end


def export_attendance_records(salon, staff_member=None, start=None,
                              end=None, event_type=None, **kwargs):
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

    ``start`` / ``end`` (aliases ``start_date`` / ``end_date``)
    are an optional window on ``recorded_at``: the defaults
    ``None`` are unbounded, so the default output is unchanged.
    See the module docstring for the range semantics. The
    window composes with ``staff_member`` (window AND record).

    ``event_type`` is optional: the default ``None`` is
    unchanged. When given, only records whose stored
    ``event_type`` exactly matches it are included. It
    composes with ``staff_member`` and the window (all AND).
    """
    start, end = _resolve_window(start, end, kwargs)
    rows = (
        AttendanceRecord.objects.filter(staff_member__salon=salon)
        .select_related("staff_member")
    )
    if staff_member is not None:
        rows = rows.filter(staff_member=staff_member)
    if event_type is not None:
        rows = rows.filter(event_type=event_type)
    start_bound = _bound(start, is_end=False)
    end_bound = _bound(end, is_end=True)
    if start_bound is not None:
        rows = rows.filter(recorded_at__gte=start_bound)
    if end_bound is not None:
        rows = rows.filter(recorded_at__lt=end_bound)
    return [_record(row) for row in rows]


def export_attendance_records_csv(salon, staff_member=None, start=None,
                                  end=None, event_type=None, **kwargs):
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

    ``start`` / ``end`` (aliases ``start_date`` / ``end_date``)
    are likewise passed through: the defaults ``None`` are
    unbounded and unchanged; a given window exports only
    records whose ``recorded_at`` falls inside it.

    ``event_type`` is likewise passed through: the default
    ``None`` is unchanged; a given value exports only records
    whose stored ``event_type`` exactly matches it.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ATTENDANCE_RECORD_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_attendance_records(
            salon, staff_member=staff_member, start=start, end=end,
            event_type=event_type, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
attendance_records_csv = export_attendance_records_csv
