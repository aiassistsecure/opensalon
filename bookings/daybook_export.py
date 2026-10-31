"""Day book CSV / dict export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports one day's day book as a list of
dicts (:func:`export_daybook`) and as a CSV string
(:func:`export_daybook_csv`) built from that same list, so the
two formats can never disagree — one source of truth.

Day book — reused, never reimplemented
--------------------------------------
Membership, cancelled exclusion, salon scoping, and ordering
come verbatim from :mod:`bookings.daybook`: this module calls
:func:`bookings.daybook.blocks_for_day` and never re-queries
appointments, re-derives roster or availability, or re-orders
rows. Ordering is exactly that service's ordering: columns by
staff display name, blocks by ``start`` within each column.
One row is exported per appointment block; a staff column with
no blocks exports no rows, so an empty day exports no dict rows
and, as CSV, the header row alone.

Columns — only fields carried by ``StaffDayColumn`` /
``AppointmentBlock``, exactly :data:`EXPORT_FIELDNAMES`:

- ``staff_member_id``: the column's / block's staff pk.
- ``staff_name``: the column's ``display_name``.
- ``online_bookable``: the column's per-staff online-booking
  toggle.
- ``appointment_id``: the block's appointment pk.
- ``client_display_name``: the block's client display name.
- ``service_name`` / ``service_category_name``: as resolved by
  the day-book service (live service name / category, else the
  appointment's ``service_name`` snapshot and ``""``).
- ``start`` / ``end``: ISO-8601 strings, as stored.
- ``status``: the block's appointment status value (cancelled
  appointments never appear — the service excludes them).
"""
import csv
import io

from bookings.daybook import blocks_for_day

__all__ = [
    "EXPORT_FIELDNAMES",
    "DAYBOOK_FIELDNAMES",
    "DAYBOOK_EXPORT_FIELDNAMES",
    "export_daybook",
    "export_daybook_csv",
    "export_daybook_blocks",
    "export_daybook_blocks_csv",
    "daybook_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "staff_member_id",
    "staff_name",
    "online_bookable",
    "appointment_id",
    "client_display_name",
    "service_name",
    "service_category_name",
    "start",
    "end",
    "status",
]
DAYBOOK_FIELDNAMES = EXPORT_FIELDNAMES
DAYBOOK_EXPORT_FIELDNAMES = EXPORT_FIELDNAMES


def _record(column, block):
    return {
        "staff_member_id": block.staff_member_id,
        "staff_name": column.display_name,
        "online_bookable": column.online_bookable,
        "appointment_id": block.appointment_id,
        "client_display_name": block.client_display_name,
        "service_name": block.service_name,
        "service_category_name": block.service_category_name,
        "start": block.start.isoformat() if block.start else None,
        "end": block.end.isoformat() if block.end else None,
        "status": block.status,
    }


def export_daybook(salon, day):
    """Return one day's day-book blocks as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance, passed through
            unchanged to :func:`bookings.daybook.blocks_for_day`.
            ``None`` exports ``[]``.
        day: a ``datetime.date`` (or datetime), passed through
            unchanged to that service.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, one per appointment block, in the day-book
        service's ordering (staff display name, then block
        ``start``).
    """
    if salon is None:
        return []
    return [
        _record(column, block)
        for column in blocks_for_day(salon, day)
        for block in column.blocks
    ]


def export_daybook_csv(salon, day):
    """Return the day-book export as a CSV string.

    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_daybook` with the same arguments, so the
    CSV and list exports always agree. Empty exports as the
    header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_daybook(salon, day):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases matching common caller phrasing.
export_daybook_blocks = export_daybook
export_daybook_blocks_csv = export_daybook_csv
daybook_csv = export_daybook_csv
