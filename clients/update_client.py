"""Salon-scoped single-client update service. Backend only.

Mirror of :mod:`clients.optins` (``update_client_opt_ins`` shape:
dataclass result, ``None``-sentinel keyword-only fields,
``save(update_fields=[...])`` for differing fields only, no-change
saves nothing, ``changed_at=None``) for ``first_name``,
``last_name``, ``email``, ``phone``, ``active``. ``None`` means
"leave unchanged"; calling with no field is rejected. Cleaning
reuses :mod:`clients.add_client`'s cleaners verbatim (``""``
clears email/phone). Opt-ins are EXCLUDED -- owned by
:func:`clients.optins.update_client_opt_ins`, one source of truth.
Only differing fields are written, so unrelated in-memory edits
are never persisted.
"""
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from clients.add_client import (
    _FIRST_LIMIT,
    _LAST_LIMIT,
    _clean_email,
    _clean_flag,
    _clean_name,
    _clean_phone,
    _clean_salon,
)
from clients.models import Client
from saloncore.models import Salon

__all__ = [
    "ClientChange", "ClientUpdate",
    "update_client", "validate_update_client",
]

# (argument / model field) in deterministic report order.
_FIELDS = ("first_name", "last_name", "email", "phone", "active")


@dataclass(frozen=True)
class ClientChange:
    """One field's old -> new value in a client update."""

    field: str
    old_value: object
    new_value: object


@dataclass(frozen=True)
class ClientUpdate:
    """Audit-friendly result of :func:`update_client`."""

    client: Client
    salon: Salon
    first_name: str
    last_name: str
    email: str
    phone: str
    active: bool
    changed_fields: tuple = ()
    changes: tuple = ()
    changed_at: object = None

    @property
    def changed(self):
        return bool(self.changed_fields)


def _result(client, salon, changes=(), changed_at=None):
    return ClientUpdate(
        client=client, salon=salon,
        first_name=client.first_name, last_name=client.last_name,
        email=client.email, phone=client.phone, active=client.active,
        changed_fields=tuple(change.field for change in changes),
        changes=tuple(changes), changed_at=changed_at)


def validate_update_client(salon, client, *, first_name=None,
                           last_name=None, email=None, phone=None,
                           active=None):
    """Validate an ``update_client`` call, writing nothing.

    Returns cleaned fields as a dict with keys ``salon``,
    ``client``, plus one entry per field explicitly given
    (``None`` fields omitted, so omitted != cleared). Raises
    the same ``ValueError`` the writer would. Safe for
    ``--dry-run`` on every backend (including NEDB, where a
    rolled-back transaction does not undo writes).
    """
    salon = _clean_salon(salon)
    if not isinstance(client, Client) or client.pk is None:
        raise ValueError("client must be a saved Client instance")
    if client.salon_id != salon.pk:
        raise ValueError("client belongs to a different salon")
    cleaned = dict(salon=salon, client=client)
    if first_name is not None:
        cleaned["first_name"] = _clean_name(
            first_name, "first_name", _FIRST_LIMIT)
    if last_name is not None:
        cleaned["last_name"] = _clean_name(
            last_name, "last_name", _LAST_LIMIT)
    if email is not None:
        cleaned["email"] = _clean_email(email)
    if phone is not None:
        cleaned["phone"] = _clean_phone(phone)
    if active is not None:
        cleaned["active"] = _clean_flag(active, "active")
    if len(cleaned) == 2:
        raise ValueError("at least one field must be given")
    return cleaned


def update_client(salon, client, *, first_name=None, last_name=None,
                  email=None, phone=None, active=None):
    """Update one client's profile fields within ``salon``.

    ``None`` fields stay unchanged. Returns a
    :class:`ClientUpdate` (resulting values, changed fields in
    ``_FIELDS`` order, old -> new values, ``changed_at`` only
    when a change was saved). Raises ``ValueError`` -- changing
    nothing -- on any validation failure. Opt-ins never change.
    """
    cleaned = validate_update_client(
        salon, client, first_name=first_name, last_name=last_name,
        email=email, phone=phone, active=active)
    salon, client = cleaned.pop("salon"), cleaned.pop("client")
    changes = tuple(
        ClientChange(field, getattr(client, field), cleaned[field])
        for field in _FIELDS
        if field in cleaned and cleaned[field] != getattr(client, field)
    )
    if not changes:
        return _result(client, salon)
    with transaction.atomic():
        for change in changes:
            setattr(client, change.field, change.new_value)
        client.save(update_fields=[change.field for change in changes])
    return _result(client, salon, changes, timezone.now())
