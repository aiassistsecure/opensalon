"""Roster availability CSV export service for the team app.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a roster pattern, a
staff member, or an attendance record, and nothing is sent.
In particular it never checks anyone in or out.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

One source of truth: every figure comes verbatim from
:mod:`team.availability` -- :func:`~team.availability.salon_roster`
for a salon's whole roster on a day, and
:func:`~team.availability.roster_availability` for one staff
member -- called with exactly the arguments given here. This
module does not re-query roster patterns, re-merge intervals,
re-derive the salon timezone handling, or recompute the
inactive-member exclusion or display-name ordering of those
services.

Rows flatten each
:class:`~team.availability.RosterAvailability` the services
return:

- one row per rostered interval, in the order the service
  returns them (merged, start order); and
- one row with empty interval fields for a member with no
  rostered intervals that day, so a member who is off is
  present in the export rather than silently absent.

Columns are only fields those structures actually carry:

- ``salon_id``: the staff member's salon (``RosterAvailability``
  carries no salon of its own; it is scoped through
  ``staff_member.salon``).
- ``staff_member_id`` / ``staff_name``: the result's
  ``staff_member_id`` / the staff member's ``display_name``.
- ``online_bookable``: the result's ``online_bookable`` flag,
  carried as its own column exactly as the service carries
  it -- separate from the intervals, and it never removes a
  rostered interval. Roster decides *when* someone works;
  this toggle decides *whether* they are offered through
  online booking at all.
- ``date``: the result's ``day``, ISO-8601.
- ``interval_start`` / ``interval_end``: the interval's
  ``start`` / ``end``, ISO-8601 aware datetimes in the salon
  timezone; empty on an off member's row.
- ``interval_minutes``: the interval's ``minutes``; empty on
  an off member's row.
- ``total_minutes``: the result's ``total_minutes``.
- ``is_working``: the result's ``is_working``.

Ordering is deterministic and is the services' own order:
staff in display-name order (for the salon export), intervals
in returned order. Lines end with ``"\\n"``.
"""
import csv
import io

from team.availability import roster_availability, salon_roster

__all__ = [
    "AVAILABILITY_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "availability_csv",
    "export_availability",
    "export_availability_csv",
    "export_roster_availability",
    "export_roster_availability_csv",
    "export_salon_roster",
    "export_salon_roster_csv",
    "roster_availability_csv",
    "salon_roster_csv",
]

#: Column / key order shared by the dict export and the CSV export.
AVAILABILITY_EXPORT_FIELDNAMES = [
    "salon_id",
    "staff_member_id",
    "staff_name",
    "online_bookable",
    "date",
    "interval_start",
    "interval_end",
    "interval_minutes",
    "total_minutes",
    "is_working",
]
EXPORT_FIELDNAMES = AVAILABILITY_EXPORT_FIELDNAMES


def _rows(results):
    rows = []
    for result in results:
        staff = result.staff_member
        common = {
            "salon_id": staff.salon_id,
            "staff_member_id": result.staff_member_id,
            "staff_name": staff.display_name,
            "online_bookable": bool(result.online_bookable),
            "date": result.day.isoformat() if result.day else None,
        }
        if not result.intervals:
            rows.append({
                **common,
                "interval_start": None,
                "interval_end": None,
                "interval_minutes": None,
                "total_minutes": result.total_minutes,
                "is_working": bool(result.is_working),
            })
        for interval in result.intervals:
            rows.append({
                **common,
                "interval_start": (
                    interval.start.isoformat() if interval.start else None
                ),
                "interval_end": (
                    interval.end.isoformat() if interval.end else None
                ),
                "interval_minutes": interval.minutes,
                "total_minutes": result.total_minutes,
                "is_working": bool(result.is_working),
            })
    return rows


def _csv(records):
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=AVAILABILITY_EXPORT_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(record)
    return buffer.getvalue()


def export_salon_roster(salon, day):
    """Return ``salon``'s roster for ``day`` as a list of dicts.

    Arguments are exactly those of
    :func:`team.availability.salon_roster` (``salon``, ``day``)
    and are passed through to it unchanged. Each entry is a
    dict with exactly :data:`AVAILABILITY_EXPORT_FIELDNAMES`
    keys (see the module docstring), in the service's order.
    Read-only.
    """
    return _rows(salon_roster(salon, day))


def export_salon_roster_csv(salon, day):
    """Return ``salon``'s roster for ``day`` as a CSV string.

    Arguments are the same as :func:`export_salon_roster`. The
    header row is :data:`AVAILABILITY_EXPORT_FIELDNAMES` and
    every data row comes from :func:`export_salon_roster` with
    the same arguments, so the CSV and the dict export always
    agree. A salon with no active staff exports as the header
    row alone. Lines end with ``"\\n"``. Read-only.
    """
    return _csv(export_salon_roster(salon, day))


def export_roster_availability(staff_member, day):
    """Return one member's roster availability as dict rows.

    Arguments are exactly those of
    :func:`team.availability.roster_availability`
    (``staff_member``, ``day``) and are passed through to it
    unchanged. The result is a list of dicts with exactly
    :data:`AVAILABILITY_EXPORT_FIELDNAMES` keys: one row per
    rostered interval, or one row with empty interval fields
    when the member is off that day. Read-only.
    """
    return _rows([roster_availability(staff_member, day)])


def export_roster_availability_csv(staff_member, day):
    """Return one member's roster availability as a CSV string.

    Arguments are the same as
    :func:`export_roster_availability`; every data row comes
    from that function with the same arguments, so the CSV and
    the dict export always agree. Lines end with ``"\\n"``.
    Read-only.
    """
    return _csv(export_roster_availability(staff_member, day))


#: Aliases, mirroring the naming convenience in sibling services.
export_availability = export_salon_roster
export_availability_csv = export_salon_roster_csv
salon_roster_csv = export_salon_roster_csv
availability_csv = export_salon_roster_csv
roster_availability_csv = export_roster_availability_csv
