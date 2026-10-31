"""Roster week CSV export service for the team app.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a roster pattern or a
staff member, and nothing is sent.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

One source of truth: every figure comes verbatim from
:func:`team.roster_week.roster_week`, called with exactly the
arguments given here -- this module does not re-query roster
patterns, re-merge intervals, recompute the Monday snap, the
salon scoping, the inactive-member exclusion, or the ordering
of that service.

Rows flatten the :class:`~team.roster_week.RosterWeek` the
service returns, per staff member, per day:

- one row per rostered interval on a day, in the order the
  service returns them (merged, start order); and
- one row with empty interval fields for a day with no
  rostered intervals, so an off day is present in the export
  rather than silently absent -- the export covers the whole
  week for every staff member the service returns.

Columns are only fields those structures actually carry:

- ``salon_id``: the result's ``salon_id``.
- ``week_start`` / ``week_end``: ISO-8601 dates, the result's
  Monday and its ``week_end`` (the Sunday six days later).
- ``staff_member_id`` / ``staff_name``: the entry's
  ``staff_member_id`` / ``display_name``.
- ``online_bookable``: the entry's ``online_bookable`` flag,
  carried as its own column exactly as the service carries
  it -- separate from the intervals, and it never removes a
  rostered interval (a member who is not online-bookable can
  still be booked in-salon).
- ``date``: the day's ``day``, ISO-8601.
- ``interval_start`` / ``interval_end``: the interval's
  ``start`` / ``end``, ISO-8601 aware datetimes in the salon
  timezone; empty on an off day's row.
- ``interval_minutes``: the interval's ``minutes``; empty on
  an off day's row.
- ``day_total_minutes``: the day's ``total_minutes``.
- ``is_working``: the day's ``is_working``.

Ordering is deterministic and is the service's own order:
staff entries in display-name order, days Monday through
Sunday, intervals in returned order. Lines end with ``"\\n"``.
"""
import csv
import io

from team.roster_week import roster_week

__all__ = [
    "EXPORT_FIELDNAMES",
    "ROSTER_WEEK_EXPORT_FIELDNAMES",
    "export_roster_week",
    "export_roster_week_csv",
    "roster_week_csv",
]

#: Column / key order shared by the dict export and the CSV export.
ROSTER_WEEK_EXPORT_FIELDNAMES = [
    "salon_id",
    "week_start",
    "week_end",
    "staff_member_id",
    "staff_name",
    "online_bookable",
    "date",
    "interval_start",
    "interval_end",
    "interval_minutes",
    "day_total_minutes",
    "is_working",
]
EXPORT_FIELDNAMES = ROSTER_WEEK_EXPORT_FIELDNAMES


def _rows(result):
    base = {
        "salon_id": result.salon_id,
        "week_start": (
            result.week_start.isoformat() if result.week_start else None
        ),
        "week_end": (
            result.week_end.isoformat() if result.week_end else None
        ),
    }
    rows = []
    for entry in result.entries:
        staff = {
            "staff_member_id": entry.staff_member_id,
            "staff_name": entry.display_name,
            "online_bookable": bool(entry.online_bookable),
        }
        for day in entry.days:
            common = {
                **base,
                **staff,
                "date": day.day.isoformat() if day.day else None,
            }
            if not day.intervals:
                rows.append({
                    **common,
                    "interval_start": None,
                    "interval_end": None,
                    "interval_minutes": None,
                    "day_total_minutes": day.total_minutes,
                    "is_working": bool(day.is_working),
                })
            for interval in day.intervals:
                rows.append({
                    **common,
                    "interval_start": (
                        interval.start.isoformat()
                        if interval.start else None
                    ),
                    "interval_end": (
                        interval.end.isoformat()
                        if interval.end else None
                    ),
                    "interval_minutes": interval.minutes,
                    "day_total_minutes": day.total_minutes,
                    "is_working": bool(day.is_working),
                })
    return rows


def export_roster_week(salon, week_start):
    """Return ``salon``'s roster week as a list of dicts.

    Arguments are exactly those of
    :func:`team.roster_week.roster_week` (``salon``,
    ``week_start``) and are passed through to it unchanged --
    including its ``ValueError`` for a missing salon or
    week-start, and its Monday snap for a non-Monday date.
    Each entry is a dict with exactly
    :data:`ROSTER_WEEK_EXPORT_FIELDNAMES` keys (see the module
    docstring), in the service's order. Read-only.
    """
    return _rows(roster_week(salon, week_start))


def export_roster_week_csv(salon, week_start):
    """Return ``salon``'s roster week as a CSV string.

    Arguments are the same as :func:`export_roster_week`. The
    header row is :data:`ROSTER_WEEK_EXPORT_FIELDNAMES` and
    every data row comes from :func:`export_roster_week` with
    the same arguments, so the CSV and the dict export always
    agree. A salon with no active staff exports as the header
    row alone. Lines end with ``"\\n"``. Read-only.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ROSTER_WEEK_EXPORT_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()
    for record in export_roster_week(salon, week_start):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
roster_week_csv = export_roster_week_csv
