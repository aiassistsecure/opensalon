"""Salon-scoped staff search service. Backend only, read-only.

Mirroring the house search shape (``catalog.search``,
``clients.note_search``): ``display_name`` and the staff level's
name match case-insensitively by substring; ``active`` and
``online_bookable`` are optional exact flag filters (``None`` =
no filter). Empty/blank/``None`` query matches every member of
the salon (subject to flags), as in ``clients.note_search``.
Only the given salon's members are ever returned. Ordering:
``display_name``, then ``id``.
"""
from django.db.models import Q

from team.models import StaffMember

__all__ = ["search_staff"]


def search_staff(salon, query=None, active=None, online_bookable=None):
    """Return ``salon``'s staff members matching the criteria.

    ``query`` is stripped and matched case-insensitively as a
    substring against ``display_name`` or the level name; blank
    matches all of the salon's members. ``active`` /
    ``online_bookable`` filter exactly when not ``None``.
    Returns a queryset with ``staff_level`` prefetched, ordered
    by display name, then id.
    """
    members = StaffMember.objects.filter(salon=salon).select_related(
        "staff_level"
    )
    text = "" if query is None else str(query).strip()
    if text:
        members = members.filter(
            Q(display_name__icontains=text)
            | Q(staff_level__name__icontains=text)
        )
    if active is not None:
        members = members.filter(active=active)
    if online_bookable is not None:
        members = members.filter(online_bookable=online_bookable)
    return members.order_by("display_name", "id")
