"""Roster-pattern write service for the team app.

Backend only -- no views, templates, or UI.

This is the single write path for ``RosterPattern`` -- the
roster book's switch in its ON position. Where a
``ShiftOverride`` (see :mod:`team.shift_overrides`) rules ONE
date only, a pattern repeats every week forever: setting a
member's pattern for one weekday replaces that weekday's
pattern wholesale with the one continuous block given, and
the pattern speaks for every future week until changed.

Semantics mirror the existing roster importer
(:mod:`team.roster_import`) exactly:

- the member is resolved in the scope the app uses -- an
  ACTIVE ``StaffMember`` of a salon (the importer's member
  set, and the roster book's); a member that does not exist
  in the database, is inactive, or carries no salon is
  rejected;
- ``weekday`` is 0 (Monday) .. 6 (Sunday), a digit string, or
  a weekday name (``Monday`` / ``mon``) -- parsed by the
  importer's ``parse_weekday``;
- ``start_time`` / ``end_time`` are ``datetime.time`` values
  or ``HH:MM[:SS]`` strings -- parsed by the importer's
  ``parse_time`` -- and end must be after start.

The model carries no break fields, so a pattern is one
continuous block and this service takes no break arguments:
there is no break state to set. Patterns are read by the one
resolver, :func:`team.availability.roster_availability`, so
service, command, roster book, day book, and online booking
can never disagree about a weekday. This module never writes
a ``ShiftOverride``.
"""
from django.core.exceptions import ValidationError

from team.models import RosterPattern, StaffMember
from team.roster_import import parse_time, parse_weekday

__all__ = [
    "preview_roster_pattern",
    "set_roster_pattern",
]


def _validate(staff_member, weekday, start_time, end_time):
    """Canonical (member, weekday, start, end) or ValidationError.

    Reads only -- writes nothing. The member returned is the
    database row for ``staff_member`` in salon scope, so a
    stale or fabricated object can never be written against.
    """
    if not isinstance(staff_member, StaffMember) \
            or staff_member.pk is None \
            or staff_member.salon_id is None:
        raise ValidationError(
            {"staff_member": "A staff member is required."})
    member = StaffMember.objects.filter(
        pk=staff_member.pk, salon_id=staff_member.salon_id,
    ).first()
    if member is None:
        raise ValidationError(
            {"staff_member": "That staff member does not exist."})
    if not member.active:
        raise ValidationError(
            {"staff_member": "That staff member is not active."})
    weekday_int = parse_weekday(weekday)
    if weekday_int is None:
        raise ValidationError(
            {"weekday": "Weekday must be 0 (Monday) to 6 (Sunday) "
                        "or a weekday name."})
    start = parse_time(start_time)
    end = parse_time(end_time)
    if start is None or end is None:
        raise ValidationError(
            "A roster pattern requires both a start and an "
            "end time.")
    if end <= start:
        raise ValidationError(
            "A roster pattern's end time must be after its "
            "start time.")
    return member, weekday_int, start, end


def preview_roster_pattern(staff_member, weekday, *,
                           start_time=None, end_time=None,
                           active=True):
    """Describe what :func:`set_roster_pattern` would do.

    Same validation as the write, reads only -- writes
    nothing, so a caller can preview safely on any store
    (no write-then-rollback). Returns a dict with the
    canonical ``staff_member``, ``weekday``, ``start_time``,
    ``end_time`` and ``active``, plus ``existing``: the
    member's current patterns for that weekday, which the
    write would replace.
    """
    member, weekday_int, start, end = _validate(
        staff_member, weekday, start_time, end_time)
    return {
        "staff_member": member,
        "weekday": weekday_int,
        "start_time": start,
        "end_time": end,
        "active": bool(active),
        "existing": list(RosterPattern.objects.filter(
            staff_member=member, weekday=weekday_int)),
    }


def set_roster_pattern(staff_member, weekday, *,
                       start_time=None, end_time=None, active=True):
    """Set ``staff_member``'s perpetual pattern for ``weekday``.

    Replaces every existing pattern for the member/weekday
    with the single given block (the switch-is-law ON write:
    the pattern, every week, forever -- never a
    ``ShiftOverride``) and returns the saved
    ``RosterPattern``. Raises ``ValidationError`` -- writing
    nothing -- for an unknown or inactive member, an invalid
    weekday, or missing/backwards times.
    """
    member, weekday_int, start, end = _validate(
        staff_member, weekday, start_time, end_time)
    RosterPattern.objects.filter(
        staff_member=member, weekday=weekday_int).delete()
    return RosterPattern.objects.create(
        staff_member=member, weekday=weekday_int,
        start_time=start, end_time=end, active=bool(active))
