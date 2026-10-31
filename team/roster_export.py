"""Roster pattern CSV export service for the team app.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a roster pattern or a
staff member, and nothing is sent.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

This module exports one salon's ``RosterPattern`` rows as a
plain, JSON-serializable list of dicts
(:func:`export_roster_patterns`) and as a CSV string
(:func:`export_roster_patterns_csv`) built from that same list,
so the two formats can never disagree -- one source of truth.
It mirrors the established export pattern in
:mod:`team.attendance_export` and :mod:`catalog.export`.

Columns are only fields the models actually carry, exactly as
``team.models`` defines them -- no invented fields:

- ``id``: the ``RosterPattern`` pk.
- ``salon_id``: the salon pk, via the pattern's staff member
  (``RosterPattern`` has no salon field of its own; patterns are
  scoped to a salon through ``StaffMember.salon``).
- ``staff_member_id`` / ``staff_name``: the staff member pk and
  its ``display_name``.
- ``staff_active``: ``StaffMember.active``, verbatim.
- ``online_bookable``: ``StaffMember.online_bookable``, the
  per-staff online-booking toggle, verbatim. It is a staff
  field, not a pattern field: roster decides *when* someone
  works and this toggle decides *whether* they are offered
  online at all (see :mod:`team.availability`), so it is
  carried as its own column and never conflated with the
  pattern's ``active``.
- ``weekday``: ``RosterPattern.weekday``, the integer value
  from ``RosterPattern.Weekday`` (0 = Monday .. 6 = Sunday).
- ``start_time`` / ``end_time``: ISO-8601 strings, as stored.
- ``active``: ``RosterPattern.active``, verbatim.

Scoping: only patterns whose staff member belongs to the given
salon are exported. ``salon=None`` exports ``[]`` (an export is
always one salon's roster).

Active / inactive: by default only active patterns are
exported, matching :mod:`catalog.export` and the roster layer
itself (``team.availability`` reads active patterns only).
Pass ``include_inactive=True`` for a complete exit export
including inactive patterns (their ``active`` field reads
``False``). Patterns of inactive staff members are not
separately filtered: their ``staff_active`` column records the
staff member's state verbatim.

Ordering is deterministic: by staff ``display_name``, then
``weekday``, then ``start_time``, then pattern ``id`` -- staff
in ``StaffMember``'s default (display-name) order, each staff
member's patterns in ``RosterPattern``'s own ordering
(weekday, start time), with ``id`` breaking any remaining tie.
Lines end with ``"\\n"``.
"""
import csv
import io

from team.models import RosterPattern

__all__ = [
    "EXPORT_FIELDNAMES",
    "ROSTER_EXPORT_FIELDNAMES",
    "export_roster",
    "export_roster_csv",
    "export_roster_patterns",
    "export_roster_patterns_csv",
    "roster_csv",
    "roster_patterns_csv",
]

#: Column / key order shared by the dict export and the CSV export.
ROSTER_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "staff_member_id",
    "staff_name",
    "staff_active",
    "online_bookable",
    "weekday",
    "start_time",
    "end_time",
    "active",
]
EXPORT_FIELDNAMES = ROSTER_EXPORT_FIELDNAMES


def _record(pattern):
    staff = pattern.staff_member
    return {
        "id": pattern.pk,
        "salon_id": staff.salon_id,
        "staff_member_id": pattern.staff_member_id,
        "staff_name": staff.display_name,
        "staff_active": bool(staff.active),
        "online_bookable": bool(staff.online_bookable),
        "weekday": pattern.weekday,
        "start_time": (
            pattern.start_time.isoformat() if pattern.start_time else None
        ),
        "end_time": (
            pattern.end_time.isoformat() if pattern.end_time else None
        ),
        "active": bool(pattern.active),
    }


def export_roster_patterns(salon, include_inactive=False):
    """Return ``salon``'s roster patterns as dict rows.

    Each entry is a dict with exactly
    :data:`ROSTER_EXPORT_FIELDNAMES` keys (see the module
    docstring). Only patterns of ``salon``'s staff members are
    included; ``salon=None`` exports ``[]``. Inactive patterns
    are excluded unless ``include_inactive=True``. Ordered by
    staff display name, then weekday, start time, and id.
    Read-only.
    """
    if salon is None:
        return []
    salon_id = getattr(salon, "pk", salon)
    patterns = (
        RosterPattern.objects.filter(staff_member__salon_id=salon_id)
        .select_related("staff_member")
        .order_by(
            "staff_member__display_name", "weekday", "start_time", "id")
    )
    if not include_inactive:
        patterns = patterns.filter(active=True)
    return [_record(pattern) for pattern in patterns]


def export_roster_patterns_csv(salon, include_inactive=False):
    """Return ``salon``'s roster patterns as a CSV string.

    The header row is :data:`ROSTER_EXPORT_FIELDNAMES` and every
    data row comes from :func:`export_roster_patterns` with the
    same arguments, so the CSV and list exports always agree.
    An empty roster exports as the header row alone. Lines end
    with ``"\\n"``. Read-only.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ROSTER_EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_roster_patterns(
            salon, include_inactive=include_inactive):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_roster = export_roster_patterns
export_roster_csv = export_roster_patterns_csv
roster_patterns_csv = export_roster_patterns_csv
roster_csv = export_roster_patterns_csv
