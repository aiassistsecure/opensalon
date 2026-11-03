"""Shift-override write service for the team app.

Backend only -- no views, templates, or UI.

This is the single write path for ``ShiftOverride`` -- the
roster book's switch in its OFF position. Where a
``RosterPattern`` repeats every week forever, an override rules
ONE date only for ONE staff member: either a single placed
shift (``start_time``/``end_time``) or a full day off
(``is_off``, no times). Undo is clearing the override, after
which the perpetual pattern speaks for the date again.

The writes here are exactly the writes the roster book's
OFF-switch made inline in ``webui.views`` (``update_or_create``
with the same defaults), and they are read by the one resolver,
:func:`team.availability.roster_availability` (override-first),
so service, command, roster book, day book, and online booking
can never disagree about a date. This module does not touch
``RosterPattern`` and never writes a perpetual pattern.
"""
import datetime

from django.core.exceptions import ValidationError

from team.models import ShiftOverride

__all__ = [
    "clear_shift_override",
    "set_shift_override",
    "undo_shift_override",
]


def _as_date(day):
    if isinstance(day, datetime.datetime):
        return day.date()
    if isinstance(day, datetime.date):
        return day
    raise ValidationError({"date": "A date is required."})


def set_shift_override(staff_member, day, *, start_time=None,
                       end_time=None, is_off=False):
    """Set ``staff_member``'s override for one ``day``.

    A placed shift requires both ``start_time`` and
    ``end_time`` (end after start); a full day off is
    ``is_off=True`` with no times. The two shapes never mix.
    An existing override for the member/date is replaced
    wholesale (``update_or_create``, as the roster book did).
    Returns the saved ``ShiftOverride``. Raises
    ``ValidationError`` -- writing nothing -- for a mixed,
    incomplete, or backwards shape.
    """
    day = _as_date(day)
    if is_off:
        if start_time is not None or end_time is not None:
            raise ValidationError(
                "A full day off takes no start/end times.")
        defaults = {"is_off": True, "start_time": None,
                    "end_time": None}
    else:
        if start_time is None or end_time is None:
            raise ValidationError(
                "A placed shift requires both a start and an "
                "end time (or is_off=True for a full day off).")
        if end_time <= start_time:
            raise ValidationError(
                "A placed shift's end time must be after its "
                "start time.")
        defaults = {"is_off": False, "start_time": start_time,
                    "end_time": end_time}
    override, _created = ShiftOverride.objects.update_or_create(
        staff_member=staff_member, date=day, defaults=defaults,
    )
    return override


def clear_shift_override(staff_member, day):
    """Clear ``staff_member``'s override for ``day`` (undo).

    Deletes the date's ``ShiftOverride`` row if one exists, so
    the perpetual ``RosterPattern`` rules the date again.
    Returns True when a row was deleted, False when the date
    had no override.
    """
    day = _as_date(day)
    deleted, _ = ShiftOverride.objects.filter(
        staff_member=staff_member, date=day,
    ).delete()
    return deleted > 0


#: Alias: undo is the roster book's word for clearing.
undo_shift_override = clear_shift_override
