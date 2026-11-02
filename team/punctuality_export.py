"""Punctuality report CSV export for the team app.

Backend only — no views, templates, or UI. Read-only.

One source of truth: every figure comes verbatim from
:func:`team.punctuality.punctuality_report`, called with
exactly the arguments given here — this module recomputes
nothing.

Columns: ``salon_id``, ``start_date`` / ``end_date``
(ISO-8601, inclusive), ``staff_member_id``, ``staff_name``,
``shifts_considered``, ``on_time_count``, ``late_count``,
``missed_count``, ``total_late_minutes`` (int),
``average_late_minutes`` (the entry's Decimal average, rendered
with two places). One row per staff entry, in the service's
order. Lines end with ``"\\n"``.
"""
import csv
import io

from team.punctuality import punctuality_report

__all__ = ["EXPORT_FIELDNAMES", "PUNCTUALITY_EXPORT_FIELDNAMES",
           "export_punctuality", "export_punctuality_csv",
           "punctuality_csv"]

PUNCTUALITY_EXPORT_FIELDNAMES = [
    "salon_id", "start_date", "end_date", "staff_member_id",
    "staff_name", "shifts_considered", "on_time_count",
    "late_count", "missed_count", "total_late_minutes",
    "average_late_minutes",
]
EXPORT_FIELDNAMES = PUNCTUALITY_EXPORT_FIELDNAMES


def _rows(result):
    base = {
        "salon_id": result.salon_id,
        "start_date": result.start_date.isoformat() if result.start_date else None,
        "end_date": result.end_date.isoformat() if result.end_date else None,
    }
    return [{
        **base,
        "staff_member_id": e.staff_member_id,
        "staff_name": e.display_name,
        "shifts_considered": e.shifts_considered,
        "on_time_count": e.on_time_count,
        "late_count": e.late_count,
        "missed_count": e.missed_count,
        "total_late_minutes": e.total_late_minutes,
        "average_late_minutes": str(e.average_late_minutes),
    } for e in result.per_staff]


def export_punctuality(*args, **kwargs):
    """Return the punctuality report as a list of dicts. Read-only."""
    return _rows(punctuality_report(*args, **kwargs))


def export_punctuality_csv(*args, **kwargs):
    """Return the punctuality report as a CSV string. Read-only."""
    result = punctuality_report(*args, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PUNCTUALITY_EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in _rows(result):
        writer.writerow(record)
    return buffer.getvalue()


punctuality_csv = export_punctuality_csv
