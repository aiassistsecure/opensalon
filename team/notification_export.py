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
recompute anything. ``created_at`` / ``seen_at`` are rendered
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


def export_staff_notifications(salon):
    """Return ``salon``'s staff notifications as a list of dicts.

    The argument is exactly that of
    :func:`team.notifications.staff_notifications` and is passed
    through unchanged. Each entry is a dict with exactly
    :data:`NOTIFICATION_EXPORT_FIELDNAMES` keys, in the
    service's order (newest first). Read-only.
    """
    return [_record(note) for note in staff_notifications(salon)]


def export_staff_notifications_csv(salon):
    """Return ``salon``'s staff notifications as a CSV string.

    The header row is :data:`NOTIFICATION_EXPORT_FIELDNAMES`
    and every data row is rendered from
    :func:`export_staff_notifications` with the same argument,
    so the CSV and the dict export can never disagree. Lines
    end with ``"\\n"``. Read-only.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NOTIFICATION_EXPORT_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for record in export_staff_notifications(salon):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
staff_notifications_csv = export_staff_notifications_csv
