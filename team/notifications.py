"""Staff notification listing + writer service.

Backend only. This is the one source of truth for
:class:`~team.models.StaffNotification` rows: which rows
belong to a salon (the listing half, read-only, exactly as
stored) and how rows are written and marked seen (the
writer half).

The writer half is exactly the writes ``webui`` made inline:
check-in creates one ping via
``StaffNotification.objects.create(staff_member=...,
appointment=..., kind="arrived")`` (``webui.views._do_status``),
and My Day marks a member's unseen pings seen via a queryset
``update(seen_at=timezone.now())``. Moving them here means
service, commands, and webui can never disagree about a ping.
No transport, no vendor: a ping is an account fact.
"""
from django.core.exceptions import ValidationError
from django.utils import timezone

from team.models import StaffNotification

__all__ = [
    "mark_seen", "notify_staff", "staff_notifications",
    "unseen_notification_count", "validate_notify_staff",
]


def staff_notifications(salon):
    """Return ``salon``'s staff notifications as a queryset.

    Rows are the stored ``StaffNotification`` records verbatim,
    with ``staff_member`` and ``appointment`` prefetched,
    ordered by ``-created_at``, then ``-id``. Only notifications
    for staff members of ``salon`` are ever returned. Read-only.
    """
    return (
        StaffNotification.objects.filter(staff_member__salon=salon)
        .select_related("staff_member", "appointment")
        .order_by("-created_at", "-id")
    )


def validate_notify_staff(member, appointment, kind="arrived"):
    """Validate a ``notify_staff`` call, writing nothing.

    Performs every check :func:`notify_staff` performs and
    returns the normalized ``kind`` the writer would store.
    Raises the same ``ValidationError`` the writer would
    raise. Writes nothing, so it is safe for ``--dry-run``
    previews on every backend (including NEDB, where a
    rolled-back transaction does not undo writes).
    """
    if member is None:
        raise ValidationError("A staff member is required.")
    if appointment is None:
        raise ValidationError("An appointment is required.")
    kind = str(kind).strip() if kind is not None else ""
    if not kind:
        raise ValidationError("A notification kind is required.")
    return kind


def unseen_notification_count(member):
    """Return how many of ``member``'s notifications are unseen.

    Read-only: exactly the rows :func:`mark_seen` would stamp
    (that member's rows where ``seen_at`` is null), counted
    without stamping any of them.
    """
    if member is None:
        raise ValidationError("A staff member is required.")
    return StaffNotification.objects.filter(
        staff_member=member, seen_at__isnull=True
    ).count()


def notify_staff(member, appointment, kind="arrived"):
    """Create one notification ping for ``member``.

    The arrival ping's exact shape, as ``webui`` created it:
    ``staff_member=member``, ``appointment=appointment``,
    ``kind=kind`` (``"arrived"`` by default), ``seen_at`` left
    unset. No de-duplication -- an undo and a fresh check-in
    is a new arrival and pings again. Returns the saved
    ``StaffNotification``. Raises ``ValidationError`` --
    writing nothing -- for a missing member/appointment or
    a blank kind.
    """
    kind = validate_notify_staff(member, appointment, kind)
    return StaffNotification.objects.create(
        staff_member=member, appointment=appointment, kind=kind
    )


def mark_seen(member):
    """Mark ``member``'s unseen notifications seen.

    Stamps ``seen_at`` to now on exactly that member's rows
    where ``seen_at`` is null -- the queryset update My Day
    performed when showing the pings. Already-seen rows and
    other members' rows are untouched. Returns the number
    of rows stamped (0 when nothing was unseen).
    """
    if member is None:
        raise ValidationError("A staff member is required.")
    return StaffNotification.objects.filter(
        staff_member=member, seen_at__isnull=True
    ).update(seen_at=timezone.now())
