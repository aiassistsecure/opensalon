"""Staff notification CSV export service for the team app.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a notification or a
staff member, and nothing is sent.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export.

One source of truth: every row comes verbatim from
:func:`team.notifications.staff_notifications`, called with
exactly the argument given here -- this module does not
re-query notifications, re-implement the salon scoping, or
recompute anything.

Per-staff-member filter: both export functions accept an
optional ``staff_member`` (default ``None``). With ``None``
the output is the salon-wide export, unchanged. With a staff
member, only that member's notifications are included; the
salon scoping still applies, so a staff member from another
salon exports as empty.

Kind filter: both export functions also accept an optional
``kind`` (default ``None``). With ``None`` the output is
unchanged. With a kind, only notifications whose stored
``kind`` exactly equals it are included. The kind filter
composes with ``staff_member`` (both must match).

Seen filter: both export functions also accept an optional
``seen`` (default ``None``). With ``None`` the output is
unchanged. With ``True``, only notifications whose
``seen_at`` is not null are included; with ``False``, only
those whose ``seen_at`` is null. The seen filter composes
with ``staff_member`` and ``kind`` (all must match).

Date window: both export functions also accept an optional
``start`` / ``end`` window pair (aliases ``start_date`` /
``end_date`` and ``date_from`` / ``date_to``), filtering on
``created_at`` -- the shape the XI attendance-records window
uses in this app. Each bound may be a ``date``, a
``datetime``, an ISO string, or ``None`` (the default,
unbounded -- with both ``None`` the output is unchanged).
The range is start-inclusive and end-exclusive after
normalisation: a ``date`` start means the start of that
day, and a ``date`` end means the start of the *following*
day, so passing two dates includes the whole end day. A
``datetime`` is used as given (naive datetimes are
interpreted in the current time zone). A reversed window
exports as empty. The window composes with ``staff_member``,
``kind``, and ``seen`` (all must match).

``created_at`` / ``seen_at`` are rendered
ISO-8601 exactly as stored (``seen_at`` empty when the row is
unseen); ``kind`` is the stored string.

Columns are only fields the row actually carries:
``id``, ``salon_id`` (the staff member's salon),
``staff_member_id`` / ``staff_name`` (the member's
``display_name``), ``appointment_id``, ``kind``,
``created_at``, and ``seen_at``.

Deliberately excluded: the staff member's ``pin`` (a
credential) and ``email`` (contact detail), as in the team
staff search export -- an export of notification rows never
carries either. No notifications exports as ``[]`` / the
header row alone. Lines end with ``"\\n"``.
"""
import csv
import io
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from team.notifications import staff_notifications

__all__ = [
    "EXPORT_FIELDNAMES",
    "NOTIFICATION_EXPORT_FIELDNAMES",
    "export_staff_notifications",
    "export_staff_notifications_csv",
    "staff_notifications_csv",
]

#: Column / key order shared by the dict export and the CSV export.
NOTIFICATION_EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "staff_member_id",
    "staff_name",
    "appointment_id",
    "kind",
    "created_at",
    "seen_at",
]
EXPORT_FIELDNAMES = NOTIFICATION_EXPORT_FIELDNAMES


def _record(note):
    return {
        "id": note.pk,
        "salon_id": note.staff_member.salon_id,
        "staff_member_id": note.staff_member_id,
        "staff_name": note.staff_member.display_name,
        "appointment_id": note.appointment_id,
        "kind": note.kind,
        "created_at": (
            note.created_at.isoformat() if note.created_at else None
        ),
        "seen_at": note.seen_at.isoformat() if note.seen_at else None,
    }


def _bound(value, *, is_end):
    """Normalise a range bound to an aware datetime or ``None``."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        try:
            value = date.fromisoformat(text)
        except ValueError:
            try:
                value = datetime.fromisoformat(
                    text[:-1] + "+00:00"
                    if text.endswith(("Z", "z")) else text)
            except ValueError as exc:
                raise ValueError(
                    "range bounds must be a date, datetime, or None"
                ) from exc
    if isinstance(value, datetime):
        bound = value
    elif isinstance(value, date):
        bound = datetime.combine(value, time.min)
        if is_end:
            bound += timedelta(days=1)
    else:
        raise ValueError("range bounds must be a date, datetime, or None")
    if timezone.is_naive(bound):
        bound = timezone.make_aware(bound, timezone.get_current_timezone())
    return bound


def _resolve_window(start, end, kwargs):
    """Fold the ``start_date`` / ``end_date`` aliases into start/end."""
    if "start_date" in kwargs:
        if start is not None:
            raise TypeError("multiple values for start")
        start = kwargs.pop("start_date")
    if "end_date" in kwargs:
        if end is not None:
            raise TypeError("multiple values for end")
        end = kwargs.pop("end_date")
    if "date_from" in kwargs:
        if start is not None:
            raise TypeError("multiple values for start")
        start = kwargs.pop("date_from")
    if "date_to" in kwargs:
        if end is not None:
            raise TypeError("multiple values for end")
        end = kwargs.pop("date_to")
    if kwargs:
        raise TypeError(
            f"unexpected arguments: {', '.join(sorted(kwargs))}")
    return start, end


def export_staff_notifications(salon, staff_member=None, kind=None,
                               seen=None, start=None, end=None, **kwargs):
    """Return ``salon``'s staff notifications as a list of dicts.

    The ``salon`` argument is exactly that of
    :func:`team.notifications.staff_notifications` and is passed
    through unchanged. Each entry is a dict with exactly
    :data:`NOTIFICATION_EXPORT_FIELDNAMES` keys, in the
    service's order (newest first). Read-only.

    ``staff_member`` is optional: the default ``None`` is the
    salon-wide export, unchanged. When a staff member is given,
    only that member's notifications are included; a staff
    member belonging to another salon exports as ``[]`` because
    the salon scoping still applies.

    ``kind`` is optional: the default ``None`` is unchanged.
    When a kind is given, only notifications whose stored
    ``kind`` exactly equals it are included. It composes with
    ``staff_member`` (both must match).

    ``seen`` is optional: the default ``None`` is unchanged.
    ``True`` includes only notifications whose ``seen_at`` is
    not null; ``False`` only those whose ``seen_at`` is null.
    It composes with ``staff_member`` and ``kind``.

    ``start`` / ``end`` (aliases ``start_date`` / ``end_date``)
    are an optional window on ``created_at``: the defaults
    ``None`` are unbounded, so the default output is unchanged.
    See the module docstring for the range semantics. The
    window composes with ``staff_member``, ``kind``, and
    ``seen`` (all must match).
    """
    start, end = _resolve_window(start, end, kwargs)
    start_bound = _bound(start, is_end=False)
    end_bound = _bound(end, is_end=True)
    return [
        _record(note) for note in staff_notifications(salon)
        if (staff_member is None
            or note.staff_member_id == staff_member.pk)
        and (kind is None or note.kind == kind)
        and (seen is None or (note.seen_at is not None) == seen)
        and (start_bound is None
             or (note.created_at is not None
                 and note.created_at >= start_bound))
        and (end_bound is None
             or (note.created_at is not None
                 and note.created_at < end_bound))
    ]


def export_staff_notifications_csv(salon, staff_member=None, kind=None,
                                   seen=None, start=None, end=None,
                                   **kwargs):
    """Return ``salon``'s staff notifications as a CSV string.

    The header row is :data:`NOTIFICATION_EXPORT_FIELDNAMES`
    and every data row is rendered from
    :func:`export_staff_notifications` with the same arguments,
    so the CSV and the dict export can never disagree. Lines
    end with ``"\\n"``. Read-only.

    ``staff_member`` is optional and passed through to
    :func:`export_staff_notifications`: the default ``None`` is
    the salon-wide export, unchanged; a given staff member
    exports only that member's notifications (header alone when
    that member has none, or belongs to another salon).

    ``kind`` is optional and passed through likewise: the
    default ``None`` is unchanged; a given kind exports only
    notifications whose stored ``kind`` exactly equals it
    (header alone when none match).

    ``seen`` is optional and passed through likewise: the
    default ``None`` is unchanged; ``True`` exports only seen
    notifications, ``False`` only unseen (header alone when
    none match).

    ``start`` / ``end`` (aliases ``start_date`` / ``end_date``)
    are likewise passed through: the defaults ``None`` are
    unbounded and unchanged; a given window exports only
    notifications whose ``created_at`` falls inside it.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NOTIFICATION_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_staff_notifications(
            salon, staff_member=staff_member, kind=kind, seen=seen,
            start=start, end=end, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
staff_notifications_csv = export_staff_notifications_csv
