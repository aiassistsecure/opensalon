"""Salon-scoped staff notification listing service.

Backend only, read-only. This is the one source of truth for
which :class:`~team.models.StaffNotification` rows belong to a
salon: every notification whose staff member belongs to the
salon, exactly as stored -- no recomputation, no derived seen
state, no filtering by kind or seen status.

Ordering follows the model's own ordering (newest first),
with ``-id`` as a deterministic tie-break for rows stamped in
the same instant.
"""
from team.models import StaffNotification

__all__ = ["staff_notifications"]


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
