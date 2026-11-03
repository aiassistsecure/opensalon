"""Price-book search service for saloncore.

Backend only -- no views, templates, or UI.

:func:`search_services` is the one price-book lookup: service
``name`` and category ``name`` both match case-insensitively
by substring (``icontains``), so searching a category finds
every service in it. Scoped to one salon via
``category__salon``; inactive services excluded unless
``include_inactive=True``; ordering is the price book's own
(category ``sort_order``, category name, service name, id).
Verbatim from ``Service`` rows; nothing invented.
"""
from django.db.models import Q

from saloncore.models import Service

__all__ = ["search_services"]


def search_services(salon, query, include_inactive=False):
    """Return ``salon``'s services matching ``query``.

    ``query`` is stripped before matching; a blank,
    whitespace-only, or ``None`` query matches nothing and
    returns an empty queryset (the catalog search house shape).

    A service matches when its name or its category's name
    contains ``query`` (case-insensitive). Inactive services
    are excluded by default; pass ``include_inactive=True``
    to include them.

    Returns a queryset of :class:`saloncore.models.Service`
    (with ``category`` prefetched via ``select_related``),
    ordered by category ``sort_order``, category name,
    service name, then id, so results are deterministic.
    """
    text = "" if query is None else str(query).strip()
    if not text:
        return Service.objects.none()
    services = (
        Service.objects.filter(category__salon=salon)
        .select_related("category")
        .filter(
            Q(name__icontains=text)
            | Q(category__name__icontains=text)
        )
    )
    if not include_inactive:
        services = services.filter(active=True)
    return services.order_by(
        "category__sort_order", "category__name", "name", "id"
    )
