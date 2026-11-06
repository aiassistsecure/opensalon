"""Per-stylist utilization CSV/JSON export service.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. This module exports per-stylist utilization as a list of
dict rows (:func:`export_utilization`) and as a CSV string
(:func:`export_utilization_csv`) built from that same list, so
the two formats can never disagree. Both are built ON TOP of
:mod:`bookings.utilization` — its definitions reused verbatim,
never recomputed. Ordering is the service's: by display name.
Columns: ``staff_member_id``, ``staff_name``, ``start_date``,
``end_date``, ``appointment_count``, ``booked_minutes``,
``rostered_minutes``, ``utilization`` (fraction; ``0.0`` when
rostered is 0).
"""
import csv
import io

from bookings.utilization import staff_utilization

__all__ = [
    "UTILIZATION_FIELDNAMES",
    "export_utilization",
    "export_utilization_rows",
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


def export_utilization(salon, date_from, date_to=None):
    """Return utilization as a list of dicts.

    Parameters pass through unchanged to
    :func:`bookings.utilization.staff_utilization`. Every row
    mirrors a CSV row exactly: keys are
    :data:`UTILIZATION_FIELDNAMES` in order,
    ``staff_member_id``, ``appointment_count``,
    ``booked_minutes`` and ``rostered_minutes`` are ints,
    ``start_date`` / ``end_date`` are ISO-8601 strings (``""``
    when the report carries no date), and ``utilization`` is
    the service's fraction (``0.0`` when rostered is 0). Rows
    follow the utilization service's ordering exactly. An
    empty or reversed range exports an empty list.
    """
    report = staff_utilization(salon, date_from, date_to)
    return [{
        "staff_member_id": row.staff_member_id,
        "staff_name": row.display_name,
        "start_date": report.start_date.isoformat() if report.start_date else "",
        "end_date": report.end_date.isoformat() if report.end_date else "",
        "appointment_count": row.appointment_count,
        "booked_minutes": row.booked_minutes,
        "rostered_minutes": row.rostered_minutes,
        "utilization": row.utilization,
    } for row in report.by_staff]


def export_utilization_csv(salon, date_from, date_to=None):
    """Return utilization CSV; parameters pass through unchanged
    to :func:`bookings.utilization.staff_utilization`. Built from
    :func:`export_utilization` with the same arguments, so the
    CSV and dict exports always agree and the historical CSV
    output is byte-identical. Empty or reversed range exports
    the header alone. Lines end ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=UTILIZATION_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in export_utilization(salon, date_from, date_to):
        writer.writerow(row)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_utilization_rows = export_utilization
utilization_csv = export_utilization_csv
