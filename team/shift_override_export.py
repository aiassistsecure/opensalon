"""Shift override CSV export service for the team app.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a shift override or
a staff member.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

One source of truth: every row is a stored
:class:`team.models.ShiftOverride` row, verbatim -- this
module does not resolve availability, consult
:mod:`team.availability`, or compute anything new. A placed
shift exports its stored ``start_time`` / ``end_time``; a
full day off exports ``is_off`` with its stored (empty)
times, exactly as stored. The resolver's reading of an
override stays in ``team.availability`` and is not this
export's business.

Scoping: a salon's overrides are the rows whose staff member
belongs to that salon (``staff_member__salon``), in the
model's own ordering (date).

Per-staff-member filter: both export functions accept an
optional ``staff_member`` (default ``None``). With ``None``
the output is the salon-wide export, unchanged. With a staff
member, only that member's overrides are included; the salon
filter still applies, so a staff member from another salon
exports as empty.

Is-off selection: both export functions also accept an
optional ``is_off`` (default ``None``). With ``None`` the
output is unchanged. With ``True`` only full-day-off rows
(stored ``is_off`` true) are included; with ``False`` only
placed-shift rows (stored ``is_off`` false). It composes
with the staff-member and date-window filters (all must
match).

Date window: both export functions also accept an optional
``start_date`` / ``end_date`` window pair, filtering on the
override's own ``date`` as inclusive salon-local dates (each
row carries one date -- the window is a date-range selector).
Each bound may be a ``date``, a ``datetime``, an ISO string,
or ``None`` (the default, unbounded -- with both ``None``
the output is unchanged, byte-identical). A ``datetime`` is
reduced to its salon-local date. Either bound may be given
alone (an open-ended window); a reversed window exports as
empty. The window composes with the staff-member filter
(window AND member). The ``start`` / ``end`` and
``date_from`` / ``date_to`` spellings are accepted as keyword
aliases, mirroring the sibling Family XI window exports.

Columns are only fields the row and its stored relation
actually carry: ``id``, ``salon_id`` (the staff member's
salon), ``staff_member_id`` / ``staff_name`` (the member's
``display_name``), ``date`` (ISO-8601, as stored), ``is_off``
(the stored boolean), and ``start_time`` / ``end_time``
(ISO-8601, empty when the row stores none -- a full day off).

Deliberately excluded: the staff member's ``pin`` (a
credential) and ``email`` (contact detail), as in the other
team exports. No rows exports as ``[]`` / the header row
alone. Lines end with ``"\\n"``.
"""
import csv
import datetime
import io
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from team.models import ShiftOverride

__all__ = [
    "EXPORT_FIELDNAMES",
    "SHIFT_OVERRIDE_EXPORT_FIELDNAMES",
    "export_shift_overrides",
    "export_shift_overrides_csv",
    "shift_overrides_csv",
]

#: Column / key order shared by the dict export and the CSV export.
SHIFT_OVERRIDE_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "staff_member_id",
    "staff_name",
    "date",
    "is_off",
    "start_time",
    "end_time",
]
EXPORT_FIELDNAMES = SHIFT_OVERRIDE_EXPORT_FIELDNAMES


def _record(row):
    return {
        "id": row.pk,
        "salon_id": row.staff_member.salon_id,
        "staff_member_id": row.staff_member_id,
        "staff_name": row.staff_member.display_name,
        "date": row.date.isoformat() if row.date else None,
        "is_off": bool(row.is_off),
        "start_time": (
            row.start_time.isoformat() if row.start_time else None
        ),
        "end_time": (
            row.end_time.isoformat() if row.end_time else None
        ),
    }


def _tz(salon):
    try:
        return ZoneInfo(salon.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_local_date(value, salon):
    """Reduce a date / datetime / ISO string to a local date."""
    if isinstance(value, datetime.datetime):
        if value.tzinfo:
            return value.astimezone(_tz(salon)).date()
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        parsed = datetime.datetime.fromisoformat(
            text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text)
        if parsed.tzinfo:
            return parsed.astimezone(_tz(salon)).date()
        return parsed.date()


def _resolve_window(start_date, end_date, kwargs):
    """Fold the alias spellings into the start_date/end_date pair."""
    if "start" in kwargs:
        if start_date is not None:
            raise TypeError("multiple values for start_date")
        start_date = kwargs.pop("start")
    if "end" in kwargs:
        if end_date is not None:
            raise TypeError("multiple values for end_date")
        end_date = kwargs.pop("end")
    if "date_from" in kwargs:
        if start_date is not None:
            raise TypeError("multiple values for start_date")
        start_date = kwargs.pop("date_from")
    if "date_to" in kwargs:
        if end_date is not None:
            raise TypeError("multiple values for end_date")
        end_date = kwargs.pop("date_to")
    if kwargs:
        raise TypeError(
            f"unexpected arguments: {', '.join(sorted(kwargs))}")
    return start_date, end_date


def export_shift_overrides(salon, staff_member=None, start_date=None,
                           end_date=None, is_off=None, **kwargs):
    """Return ``salon``'s shift overrides as a list of dicts.

    Each entry is one stored :class:`team.models.ShiftOverride`
    row of the salon, as a dict with exactly
    :data:`SHIFT_OVERRIDE_EXPORT_FIELDNAMES` keys, in the
    model's ordering (date). Read-only.

    ``staff_member`` is optional: the default ``None`` is the
    salon-wide export, unchanged. When a staff member is given,
    only that member's overrides are included; a staff member
    belonging to another salon exports as ``[]`` because the
    salon filter still applies.

    ``start_date`` / ``end_date`` are an optional inclusive
    window on the override's own ``date``: the defaults
    ``None`` are unbounded, so the default output is unchanged.
    See the module docstring for the window semantics. The
    window composes with ``staff_member`` (window AND member).

    ``is_off`` is optional: the default ``None`` is unchanged.
    ``True`` includes only full-day-off rows; ``False`` only
    placed-shift rows. It composes with ``staff_member`` and
    the window (all must match).
    """
    start_date, end_date = _resolve_window(start_date, end_date, kwargs)
    rows = (
        ShiftOverride.objects.filter(staff_member__salon=salon)
        .select_related("staff_member")
    )
    if staff_member is not None:
        rows = rows.filter(staff_member=staff_member)
    if is_off is not None:
        rows = rows.filter(is_off=bool(is_off))
    if start_date is not None:
        rows = rows.filter(date__gte=_as_local_date(start_date, salon))
    if end_date is not None:
        rows = rows.filter(date__lte=_as_local_date(end_date, salon))
    return [_record(row) for row in rows]


def export_shift_overrides_csv(salon, staff_member=None, start_date=None,
                               end_date=None, is_off=None, **kwargs):
    """Return ``salon``'s shift overrides as a CSV string.

    The header row is :data:`SHIFT_OVERRIDE_EXPORT_FIELDNAMES`
    and every data row is rendered from
    :func:`export_shift_overrides` with the same arguments, so
    the CSV and the dict export can never disagree. Lines end
    with ``"\\n"``. Read-only.

    ``staff_member`` is optional and passed through to
    :func:`export_shift_overrides`: the default ``None`` is
    the salon-wide export, unchanged; a given staff member
    exports only that member's overrides (header alone when that
    member has none, or belongs to another salon).

    ``start_date`` / ``end_date`` are likewise passed through:
    the defaults ``None`` are unbounded and unchanged; a given
    window exports only overrides whose ``date`` falls inside
    it (header alone for a reversed window).

    ``is_off`` is likewise passed through: the default
    ``None`` is unchanged; ``True`` exports only full-day-off
    rows, ``False`` only placed-shift rows (header alone when
    none match).
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=SHIFT_OVERRIDE_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_shift_overrides(
            salon, staff_member=staff_member, start_date=start_date,
            end_date=end_date, is_off=is_off, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
shift_overrides_csv = export_shift_overrides_csv
