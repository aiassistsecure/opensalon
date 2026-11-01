"""Per-stylist utilization CSV export service.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. CSV built ON TOP of :mod:`bookings.utilization` — its
definitions reused verbatim, never recomputed. Ordering is the
service's: by display name. Columns: ``staff_member_id``,
``staff_name``, ``start_date``, ``end_date``,
``appointment_count``, ``booked_minutes``, ``rostered_minutes``,
``utilization`` (fraction; ``0.0`` when rostered is 0).
"""
import csv
import io

from bookings.utilization import staff_utilization

__all__ = [
    "UTILIZATION_FIELDNAMES",
    "export_utilization_csv",
    "utilization_csv",
]

UTILIZATION_FIELDNAMES = [
    "staff_member_id",
    "staff_name",
    "start_date",
    "end_date",
    "appointment_count",
    "booked_minutes",
    "rostered_minutes",
    "utilization",
]


def export_utilization_csv(salon, date_from, date_to=None):
    """Return utilization CSV; parameters pass through unchanged
    to :func:`bookings.utilization.staff_utilization`. Empty or
    reversed range exports the header alone. Lines end ``"\\n"``.
    """
    report = staff_utilization(salon, date_from, date_to)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=UTILIZATION_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in report.by_staff:
        writer.writerow({
            "staff_member_id": row.staff_member_id,
            "staff_name": row.display_name,
            "start_date": report.start_date.isoformat() if report.start_date else "",
            "end_date": report.end_date.isoformat() if report.end_date else "",
            "appointment_count": row.appointment_count,
            "booked_minutes": row.booked_minutes,
            "rostered_minutes": row.rostered_minutes,
            "utilization": row.utilization,
        })
    return buffer.getvalue()


utilization_csv = export_utilization_csv
