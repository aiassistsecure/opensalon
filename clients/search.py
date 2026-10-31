"""Salon-scoped client search.

Pure service module — no views, no UI. Every query is scoped to a
single salon: a search can never return another salon's clients.
"""
from django.db.models import Q

from clients.models import Client


def search_clients(salon, query):
    """Return ``salon``'s clients matching ``query``.

    Args:
        salon: the ``saloncore.Salon`` to search within.
        query: search text; matched case-insensitively as a substring
            against first name, last name, email, and phone. An
            empty, whitespace-only, or ``None`` query returns all of
            the salon's clients.

    Returns:
        A queryset of ``Client`` ordered deterministically by
        last name, then first name (primary key as a final
        tie-breaker for clients with identical names).
    """
    clients = Client.objects.filter(salon=salon)
    text = (query or "").strip()
    if text:
        clients = clients.filter(
            Q(first_name__icontains=text)
            | Q(last_name__icontains=text)
            | Q(email__icontains=text)
            | Q(phone__icontains=text)
        )
    return clients.order_by("last_name", "first_name", "pk")
