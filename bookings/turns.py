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


# --- Rotation: who is up next -------------------------------------------
#
# Eligibility is read from the same two sources of truth the rest of
# the product reads: the roster resolver (team.availability — who is
# working that day, overrides first) and the capability rule
# (team.capabilities — who performs a service). The per-staff online
# booking toggle is NOT applied here: it governs the online door,
# and the turn queue is the in-salon floor.

from datetime import datetime, timezone as _dt_timezone

from django.utils import timezone

from team.availability import salon_roster
from team.capabilities import performer_ids

_NEVER = datetime.min.replace(tzinfo=_dt_timezone.utc)


def eligible_staff(salon, on_date, service=None):
    """Members working ``on_date`` at ``salon``, capability-filtered.

    When ``service`` is given, only members who perform it (per the
    capability rule) are eligible; an open service restricts nobody.
    Ordered by display name (StaffMember's default ordering).
    """
    if salon is None or on_date is None:
        return []
    members = [
        avail.staff_member
        for avail in salon_roster(salon, on_date)
        if avail.is_working
    ]
    if service is not None:
        ids = performer_ids(salon, service)
        if ids is not None:
            members = [m for m in members if m.pk in ids]
    return members


def _last_taken_at(salon, staff_member, on_date):
    """When ``staff_member`` last took a turn at ``salon`` that day."""
    rows = TurnEntry.objects.filter(
        salon=salon,
        assigned_staff=staff_member,
        status__in=TAKEN_STATUSES,
        created_at__date=on_date,
    ).order_by("-created_at", "-pk")
    entry = rows.first()
    return entry.created_at if entry else None


def next_up(salon, on_date, service=None):
    """The member whose turn it is, or None when nobody is eligible.

    Fairness order: fewest turns taken today first; among equals,
    the member whose last turn was longest ago (never today = first);
    member id breaks any remaining tie, so the answer is stable.
    """
    members = eligible_staff(salon, on_date, service=service)
    if not members:
        return None

    def key(member):
        last = _last_taken_at(salon, member, on_date)
        return (
            turns_taken_today(salon, member, on_date),
            last if last is not None else _NEVER,
            member.pk,
        )

    return min(members, key=key)


def call_next(salon, on_date):
    """Call the head of the queue: assign the member who is up.

    The entry's own service decides capability. Returns the called
    entry, or None when the queue is empty or nobody eligible is
    working. A guest's requested_staff is a preference recorded on
    the entry — rotation, not the request, decides who is called.
    """
    entry = waiting_queue(salon).first()
    if entry is None:
        return None
    member = next_up(salon, on_date, service=entry.service)
    if member is None:
        return None
    entry.assigned_staff = member
    entry.status = TurnEntry.Status.CALLED
    entry.called_at = timezone.now()
    entry.save(update_fields=["assigned_staff", "status", "called_at", "updated_at"])
    return entry
