"""Roster variance CSV export for the team app.

Backend only — no views, templates, or UI. Read-only.

One source of truth: every figure comes verbatim from
:func:`team.variance.roster_variance`, called with exactly the
arguments given here — this module recomputes nothing.

Columns: ``salon_id``, ``start_date`` / ``end_date`` (ISO-8601,
inclusive), ``staff_member_id``, ``staff_name``,
``rostered_minutes``, ``actual_minutes``, ``variance_minutes``
(actual − rostered), ``days_rostered``, ``days_attended``,
``absence_days``. One row per staff entry, in the service's
order. Lines end with ``"\\n"``.
"""
import csv
import io

from team.variance import roster_variance

__all__ = ["EXPORT_FIELDNAMES", "VARIANCE_EXPORT_FIELDNAMES",
           "export_roster_variance", "export_roster_variance_csv",
           "roster_variance_csv"]

VARIANCE_EXPORT_FIELDNAMES = [
    "salon_id", "start_date", "end_date", "staff_member_id",
    "staff_name", "rostered_minutes", "actual_minutes",
    "variance_minutes", "days_rostered", "days_attended",
    "absence_days",
]
EXPORT_FIELDNAMES = VARIANCE_EXPORT_FIELDNAMES


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
        "rostered_minutes": e.rostered_minutes,
        "actual_minutes": e.actual_minutes,
        "variance_minutes": e.variance_minutes,
        "days_rostered": e.days_rostered,
        "days_attended": e.days_attended,
        "absence_days": e.absence_days,
    } for e in result.per_staff]


def export_roster_variance(*args, **kwargs):
    """Return the roster variance as a list of dicts. Read-only."""
    return _rows(roster_variance(*args, **kwargs))


def export_roster_variance_csv(*args, **kwargs):
    """Return the roster variance as a CSV string. Read-only."""
    result = roster_variance(*args, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=VARIANCE_EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in _rows(result):
        writer.writerow(record)
    return buffer.getvalue()


roster_variance_csv = export_roster_variance_csv
