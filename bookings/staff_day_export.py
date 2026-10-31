"""Staff day CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports one day's per-staff load as a
CSV string built ON TOP of :mod:`bookings.staff_day` — the
definition of a day's load (day membership by overlap, cancelled
exclusion, booked minutes, first/last times, salon scoping,
ordering) is that service's alone and is reused verbatim via
:func:`bookings.staff_day.staff_day_load`; this module never
recomputes a load, re-queries appointments, or re-orders rows.
Ordering is exactly the service's ordering: by the staff member's
display name.

Columns are only fields carried by the service's
``StaffDayLoad`` entries:

- ``staff_member_id``: the staff member's pk.
- ``staff_name``: the staff member's display name.
- ``appointment_count``: non-cancelled appointments that day.
- ``booked_minutes``: sum of appointment durations, whole minutes.
- ``first_start`` / ``last_start`` / ``last_end``: ISO-8601
  strings for the earliest start, latest start, and latest end,
  or empty when the staff member has no counted appointment.
"""
import csv
import io

from bookings.staff_day import staff_day_load

__all__ = [
    "STAFF_DAY_FIELDNAMES",
    "export_staff_day_csv",
    "staff_day_csv",
]

#: Column order of the CSV export.
STAFF_DAY_FIELDNAMES = [
    "staff_member_id",
    "staff_name",
    "appointment_count",
    "booked_minutes",
    "first_start",
    "last_start",
    "last_end",
]


def _iso(value):
    return value.isoformat() if value else ""


def export_staff_day_csv(salon_or_day, day=None):
    """Return one day's per-staff load as a CSV string.

    Accepts exactly the parameters of
    :func:`bookings.staff_day.staff_day_load`, passed through
    unchanged: either ``export_staff_day_csv(salon, day)`` — one row
    per active staff member of ``salon``, including zero-load
    staff — or ``export_staff_day_csv(day)`` — one row per staff
    member with a counted appointment that day.

    Returns:
        A CSV string whose header row is
        :data:`STAFF_DAY_FIELDNAMES` and whose data rows follow the
        staff-day service's ordering exactly. The salon form of an
        empty day exports one zero-load row per active staff
        member; the date-only form exports the header row alone.
        Lines end with ``"\\n"``.
    """
    loads = staff_day_load(salon_or_day, day)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=STAFF_DAY_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for load in loads:
        writer.writerow({
            "staff_member_id": load.staff_member_id,
            "staff_name": load.display_name,
            "appointment_count": load.appointment_count,
            "booked_minutes": load.booked_minutes,
            "first_start": _iso(load.first_start),
            "last_start": _iso(load.last_start),
            "last_end": _iso(load.last_end),
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
staff_day_csv = export_staff_day_csv
