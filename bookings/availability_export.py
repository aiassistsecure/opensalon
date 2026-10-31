"""Available-slots CSV / dict export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment, roster
pattern, or any other record.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports one day's available slots as a
list of dicts (:func:`export_available_slots`) and as a CSV string
(:func:`export_available_slots_csv`) built from that same list, so
the two formats can never disagree — one source of truth.

Availability — reused, never reimplemented
------------------------------------------
Roster windows, appointment subtraction, interval merging, the
service-length filter, and the online-booking toggle handling
come verbatim from :mod:`bookings.availability`: this module
calls :func:`bookings.availability.available_slots` and never
re-queries roster patterns or appointments, re-derives free time,
or re-orders rows. Ordering is exactly that service's ordering:
staff by display name (StaffMember's default ordering), then
intervals in the order that service returns them. One row is
exported per free interval; a staff member with a roster window
but no free intervals left exports no rows, and a day with no
rostered staff exports no dict rows and, as CSV, the header row
alone.

Columns — only fields carried by ``StaffAvailability`` /
``FreeInterval``, exactly :data:`EXPORT_FIELDNAMES`:

- ``salon_id``: the salon the export was scoped to.
- ``staff_member_id``: the availability entry's staff pk.
- ``staff_name``: the staff member's ``display_name``.
- ``online_bookable``: the entry's per-staff online-booking
  toggle, as flagged by the service.
- ``start`` / ``end``: ISO-8601 strings for the free interval.
- ``minutes``: the interval's whole minutes
  (``FreeInterval.minutes``).
"""
import csv
import io

from bookings.availability import available_slots

__all__ = [
    "EXPORT_FIELDNAMES",
    "AVAILABILITY_FIELDNAMES",
    "AVAILABLE_SLOTS_FIELDNAMES",
    "export_available_slots",
    "export_available_slots_csv",
    "export_availability",
    "export_availability_csv",
    "availability_csv",
    "available_slots_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "salon_id",
    "staff_member_id",
    "staff_name",
    "online_bookable",
    "start",
    "end",
    "minutes",
]
AVAILABILITY_FIELDNAMES = EXPORT_FIELDNAMES
AVAILABLE_SLOTS_FIELDNAMES = EXPORT_FIELDNAMES


def _record(salon, entry, interval):
    return {
        "salon_id": salon.pk if salon is not None else None,
        "staff_member_id": entry.staff_member_id,
        "staff_name": entry.staff_member.display_name,
        "online_bookable": entry.online_bookable,
        "start": interval.start.isoformat() if interval.start else None,
        "end": interval.end.isoformat() if interval.end else None,
        "minutes": interval.minutes,
    }


def export_available_slots(salon, day, service=None, *, online_only=False):
    """Return one day's available slots as dict rows.

    Args:
        salon: ``saloncore.Salon`` instance, passed through
            unchanged to :func:`bookings.availability.available_slots`.
            ``None`` exports ``[]``.
        day: a ``datetime.date`` (or datetime), passed through
            unchanged to that service.
        service: optional ``saloncore.Service``, passed through
            unchanged to that service; when given, only intervals
            at least ``service.total_minutes`` long are returned
            by the service and therefore exported.
        online_only: passed through unchanged to that service;
            when True, staff with ``online_bookable=False`` are
            excluded entirely by the service.

    Returns:
        A list of dicts with exactly :data:`EXPORT_FIELDNAMES`
        keys, one per free interval, in the availability
        service's ordering (staff display name, then interval
        order as returned by the service).
    """
    if salon is None:
        return []
    return [
        _record(salon, entry, interval)
        for entry in available_slots(
            salon, day, service=service, online_only=online_only)
        for interval in entry.intervals
    ]


def export_available_slots_csv(salon, day, service=None, *, online_only=False):
    """Return the available-slots export as a CSV string.

    Arguments are the same as :func:`export_available_slots`.
    Header is :data:`EXPORT_FIELDNAMES`; every data row comes
    from :func:`export_available_slots` with the same arguments,
    so the CSV and list exports always agree. Empty exports as
    the header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_available_slots(
            salon, day, service=service, online_only=online_only):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases matching common caller phrasing.
export_availability = export_available_slots
export_availability_csv = export_available_slots_csv
availability_csv = export_available_slots_csv
available_slots_csv = export_available_slots_csv
