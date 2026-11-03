"""Roster-pattern import service for the team app.

Backend only -- no views, templates, or UI. This is the file
counterpart to :mod:`team.roster_export`: a salon can bring its
roster in as a CSV of recurring weekly patterns instead of
re-typing every band.

One row is one :class:`team.models.RosterPattern`:

- member identifier -- resolved against the salon's ACTIVE
  staff members (the same member set
  ``import_roster_derived`` works on), first by the generic
  ``StaffMember.external_id`` (the key ``import_staff`` stores
  and appointments carry), then by internal id, then by exact
  ``display_name``. A row whose identifier resolves to nobody
  is skipped and counted (``skipped_unknown_member``) -- never
  imported against a guessed member.
- ``weekday`` -- 0 (Monday) .. 6 (Sunday), or a weekday name
  (``Monday`` / ``mon``).
- ``start_time`` / ``end_time`` (``start`` / ``end`` accepted)
  -- ``HH:MM`` or ``HH:MM:SS``; end must be after start.

Writes are ``get_or_create`` on
``(staff_member, weekday, start_time, end_time)`` -- exactly
the identity ``import_roster_derived`` uses -- so a re-run is
idempotent and an existing (human-corrected) pattern is never
overwritten or deleted. Bad rows (missing fields, unparseable
weekday/time, end not after start) are skipped and counted
(``skipped_bad_row``), never fatal. Counts only: no staff
names are returned or printed by callers.
"""
import datetime

from team.models import RosterPattern, StaffMember

__all__ = [
    "MAPPED_KEYS",
    "ROSTER_IMPORT_KEYS",
    "import_roster_rows",
    "parse_time",
    "parse_weekday",
    "resolve_member",
]

#: Every CSV column this importer maps (all accepted spellings).
MAPPED_KEYS = frozenset({
    "staff_member_external_id", "staff_member_id", "staff_name",
    "external_id", "staff_external_id", "staffId", "staff_id",
    "member", "member_id", "staff_member",
    "weekday", "start_time", "end_time", "start", "end",
})
ROSTER_IMPORT_KEYS = MAPPED_KEYS

_MEMBER_KEYS = (
    "staff_member_external_id", "external_id", "staff_external_id",
    "staffId", "staff_id", "staff_member_id", "member_id",
    "member", "staff_member", "staff_name",
)

_WEEKDAYS = {}
for _i, _name in enumerate(
        ["monday", "tuesday", "wednesday", "thursday", "friday",
         "saturday", "sunday"]):
    _WEEKDAYS[_name] = _i
    _WEEKDAYS[_name[:3]] = _i


def _text(row, keys):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def parse_weekday(value):
    """Weekday int 0..6 from an int, digit string, or name."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 6 else None
    text = str(value or "").strip().lower()
    if text.isdigit():
        number = int(text)
        return number if 0 <= number <= 6 else None
    return _WEEKDAYS.get(text)


def parse_time(value):
    """``datetime.time`` from a time or HH:MM[:SS] string."""
    if isinstance(value, datetime.time):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            return datetime.datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def _member_maps(salon):
    members = list(
        StaffMember.objects.filter(salon=salon, active=True))
    by_external = {m.external_id: m for m in members if m.external_id}
    by_id = {str(m.pk): m for m in members}
    by_name = {m.display_name: m for m in members}
    return by_external, by_id, by_name


def resolve_member(identifier, maps):
    """Member for ``identifier``: external_id, then id, then name."""
    by_external, by_id, by_name = maps
    return (by_external.get(identifier) or by_id.get(identifier)
            or by_name.get(identifier))


def import_roster_rows(salon, rows):
    """Import roster-pattern ``rows`` (dicts) into ``salon``.

    Returns a counts dict: ``created``, ``existing``,
    ``skipped``, ``skipped_unknown_member``, ``skipped_bad_row``
    (``skipped`` is the sum of the two skip counters).
    """
    stats = dict.fromkeys(
        ["created", "existing", "skipped",
         "skipped_unknown_member", "skipped_bad_row"], 0)
    maps = _member_maps(salon)
    for row in rows:
        if not isinstance(row, dict):
            stats["skipped_bad_row"] += 1
            continue
        identifier = _text(row, _MEMBER_KEYS)
        if not identifier:
            stats["skipped_bad_row"] += 1
            continue
        member = resolve_member(identifier, maps)
        if member is None:
            stats["skipped_unknown_member"] += 1
            continue
        weekday = parse_weekday(
            row.get("weekday") if "weekday" in row else None)
        start = parse_time(_text(row, ("start_time", "start")))
        end = parse_time(_text(row, ("end_time", "end")))
        if weekday is None or start is None or end is None \
                or end <= start:
            stats["skipped_bad_row"] += 1
            continue
        _pattern, created = RosterPattern.objects.get_or_create(
            staff_member=member, weekday=weekday,
            start_time=start, end_time=end)
        stats["created" if created else "existing"] += 1
    stats["skipped"] = (
        stats["skipped_unknown_member"] + stats["skipped_bad_row"])
    return stats
