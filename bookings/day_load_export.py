"""Staff day load CSV/JSON export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes an appointment.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports one day's per-staff load as a
list of dict rows (:func:`export_day_load`) and as a CSV string
(:func:`export_day_load_csv`) built from that same list, so the
two formats can never disagree. The export is built ON TOP of
:mod:`bookings.staff_day` — the definition of a day's load (day
membership by overlap, cancelled exclusion, booked minutes,
first/last times, salon scoping, ordering) is that service's
alone and is reused verbatim via
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
    "DAY_LOAD_FIELDNAMES",
    "export_day_load",
    "export_day_load_rows",
    "export_day_load_csv",
    "day_load_csv",
]

#: Column order of the CSV export.
DAY_LOAD_FIELDNAMES = [
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


def export_day_load(salon_or_day, day=None):
    """Return one day's per-staff load as a list of dicts.

    Accepts exactly the parameters of
    :func:`bookings.staff_day.staff_day_load`, passed through
    unchanged: either ``export_day_load(salon, day)`` — one row
    per active staff member of ``salon``, including zero-load
    staff — or ``export_day_load(day)`` — one row per staff
    member with a counted appointment that day.

    Every row mirrors a CSV row exactly: keys are
    :data:`DAY_LOAD_FIELDNAMES` in order, ``staff_member_id`` is
    the staff member's pk, ``appointment_count`` and
    ``booked_minutes`` are ints, and ``first_start`` /
    ``last_start`` / ``last_end`` are ISO-8601 strings (``""``
    when the staff member has no counted appointment). Rows
    follow the day-load service's ordering exactly. The salon
    form of an empty day exports one zero-load row per active
    staff member; the date-only form exports an empty list.
    Records nothing.
    """
    loads = staff_day_load(salon_or_day, day)
    return [{
        "staff_member_id": load.staff_member_id,
        "staff_name": load.display_name,
        "appointment_count": load.appointment_count,
        "booked_minutes": load.booked_minutes,
        "first_start": _iso(load.first_start),
        "last_start": _iso(load.last_start),
        "last_end": _iso(load.last_end),
    } for load in loads]


def export_day_load_csv(salon_or_day, day=None):
    """Return one day's per-staff load as a CSV string.

    Accepts exactly the parameters of
    :func:`bookings.staff_day.staff_day_load`, passed through
    unchanged: either ``export_day_load_csv(salon, day)`` — one row
    per active staff member of ``salon``, including zero-load
    staff — or ``export_day_load_csv(day)`` — one row per staff
    member with a counted appointment that day. Built from
    :func:`export_day_load` with the same arguments, so the CSV
    and dict exports always agree.

    Returns:
        A CSV string whose header row is
        :data:`DAY_LOAD_FIELDNAMES` and whose data rows follow the
        day-load service's ordering exactly. The salon form of an
        empty day exports one zero-load row per active staff
        member; the date-only form exports the header row alone.
        Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=DAY_LOAD_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in export_day_load(salon_or_day, day):
        writer.writerow(row)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_day_load_rows = export_day_load
day_load_csv = export_day_load_csv
