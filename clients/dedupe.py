"""Read-only duplicate-candidate detection for clients.

Pure service module — no views, no UI. Finds groups of active
clients that share a normalized email address or phone number, so
a human can review possible duplicates. This module NEVER merges,
updates, or deletes records; it only reads.
"""
import re

from clients.models import Client

_NON_DIGIT = re.compile(r"\D+")


def normalize_email(email):
    """Return ``email`` stripped and lowercased ('' if blank)."""
    return (email or "").strip().lower()


def normalize_phone(phone):
    """Return ``phone`` as digits only ('' if it has no digits).

    Punctuation, whitespace, and a leading US country code (``1``
    on an 11-digit number) are removed, so ``(555) 010-1234``,
    ``555.010.1234``, and ``+1 555 010 1234`` all normalize to
    ``5550101234``.
    """
    digits = _NON_DIGIT.sub("", phone or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


# (key_type, model field, normalizer) — checked in this order.
_KEYS = (
    ("email", "email", normalize_email),
    ("phone", "phone", normalize_phone),
)


def find_duplicate_candidates(salon=None):
    """Return groups of active clients sharing an email or phone.

    Args:
        salon: optional ``saloncore.Salon``; when given, only that
            salon's clients are considered, so candidates never mix
            clients from different salons. When ``None``, all
            salons' clients are considered (still grouped within
            the shared key only).

    Returns:
        A list of dicts, one per shared normalized key with at
        least two active clients::

            {"key_type": "email" | "phone",
             "key": <normalized email or phone>,
             "clients": [<Client>, ...]}

        Clients with a blank email/phone never group on that key.
        A pair sharing both email and phone appears in two groups
        (one per key type). Groups are ordered by key type then
        key; clients within a group by last name, first name, pk.
        The result is deterministic for identical data.
    """
    clients = Client.objects.filter(active=True)
    if salon is not None:
        clients = clients.filter(salon=salon)
    clients = clients.order_by("last_name", "first_name", "pk")

    groups = []
    for key_type, field, normalize in _KEYS:
        by_key = {}
        for client in clients:
            key = normalize(getattr(client, field))
            if key:
                by_key.setdefault(key, []).append(client)
        for key in sorted(by_key):
            members = by_key[key]
            if len(members) >= 2:
                groups.append(
                    {"key_type": key_type, "key": key, "clients": members}
                )
    return groups
