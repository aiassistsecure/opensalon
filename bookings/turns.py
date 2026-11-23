"""FREE TURN queue reads.

The walk-in turn queue is arrival order: the waiting entries for
a salon, oldest first. A turn counts as taken by the staff member
assigned to it once the guest is in service or done; turns are a
same-day affair, so "today" is the entry's arrival date.
"""

from bookings.models import TurnEntry

TAKEN_STATUSES = (TurnEntry.Status.IN_SERVICE, TurnEntry.Status.DONE)


def waiting_queue(salon):
    """Waiting turn entries for ``salon``, in arrival order."""
    if salon is None:
        return TurnEntry.objects.none()
    return TurnEntry.objects.filter(
        salon=salon, status=TurnEntry.Status.WAITING
    ).order_by("created_at", "pk")


def turns_taken_today(salon, staff_member, date):
    """How many turns ``staff_member`` took at ``salon`` on ``date``.

    Counts only entries that reached in service or done, credited
    to the member they were assigned to.
    """
    if salon is None or staff_member is None:
        return 0
    return TurnEntry.objects.filter(
        salon=salon,
        assigned_staff=staff_member,
        status__in=TAKEN_STATUSES,
        created_at__date=date,
    ).count()
