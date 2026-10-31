"""Salon-scoped client opt-in update service.

Pure service module -- no views, no UI. This is the write path for
a client's messaging consent; reads and sends elsewhere (search,
messaging) never change it.

One source of truth: the ``Client`` model carries a single opt-in
per channel -- ``sms_opt_in`` and ``email_opt_in`` -- and each flag
gates BOTH marketing and appointment reminders on that channel
(the same conservative mapping ``import_clients`` documents: a
channel is only on when the client consented to both uses). This
module therefore updates exactly those two flags; it does not
invent separate marketing/reminder flags.

Rules:

- Salon-scoped: the client must belong to the given salon; a
  client from another salon is rejected and never modified.
- Explicit booleans only: each flag argument is keyword-only,
  ``None`` (the default) means "leave unchanged", and any other
  non-``bool`` value is rejected. Calling with neither flag is
  rejected -- there is no silent no-op update.
- No other fields change: only flags whose value actually differs
  are written, via ``save(update_fields=[...])``, so no other
  column is ever written by this service, even if the in-memory
  instance carries unrelated unsaved edits.
- Audit-friendly: the returned :class:`OptInUpdate` records the
  old and new value of every changed flag and a ``changed_at``
  timestamp. ``Client`` has no ``updated_at`` column and clients
  have no audit-row model, so no timestamp/audit row is persisted
  here -- the result is what a caller logs if it needs a trail.
  An update that changes nothing saves nothing and reports
  ``changed_at=None`` with empty ``changed_fields``.
"""
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from clients.models import Client
from saloncore.models import Salon

__all__ = ["OptInChange", "OptInUpdate", "update_client_opt_ins"]

# (argument / model field) in deterministic report order.
_FIELDS = ("sms_opt_in", "email_opt_in")


@dataclass(frozen=True)
class OptInChange:
    """One flag's old -> new value in an opt-in update."""

    field: str
    old_value: bool
    new_value: bool


@dataclass(frozen=True)
class OptInUpdate:
    """Audit-friendly result of :func:`update_client_opt_ins`."""

    client: Client
    salon: Salon
    sms_opt_in: bool
    email_opt_in: bool
    changed_fields: tuple = ()
    changes: tuple = ()
    changed_at: object = None

    @property
    def changed(self):
        return bool(self.changed_fields)


def _clean_flag(name, value):
    if value is not None and type(value) is not bool:
        raise ValidationError({name: "Must be an explicit boolean or None."})
    return value


def update_client_opt_ins(salon, client, *, sms_opt_in=None, email_opt_in=None):
    """Update ``client``'s opt-in flags within ``salon``.

    Args:
        salon: the ``saloncore.Salon`` the client must belong to.
        client: a saved ``clients.Client`` of that salon.
        sms_opt_in: explicit ``bool`` for the SMS flag (marketing
            and reminders), or ``None`` to leave it unchanged.
        email_opt_in: explicit ``bool`` for the email flag
            (marketing and reminders), or ``None`` to leave it
            unchanged.

    Returns:
        An :class:`OptInUpdate` with the resulting flag values,
        the fields that actually changed (in ``sms_opt_in``,
        ``email_opt_in`` order), their old -> new values, and a
        ``changed_at`` timestamp when -- and only when -- a change
        was saved.

    Raises:
        ValidationError: if salon/client are not saved instances
            of the right models, the client belongs to a different
            salon, neither flag is given, or a given flag is not
            an explicit boolean. Nothing is saved in any of these
            cases.
    """
    if not isinstance(salon, Salon) or salon.pk is None:
        raise ValidationError("salon must be a saved Salon instance.")
    if not isinstance(client, Client) or client.pk is None:
        raise ValidationError("client must be a saved Client instance.")
    if client.salon_id != salon.pk:
        raise ValidationError("Client belongs to a different salon.")

    requested = {
        "sms_opt_in": _clean_flag("sms_opt_in", sms_opt_in),
        "email_opt_in": _clean_flag("email_opt_in", email_opt_in),
    }
    if all(value is None for value in requested.values()):
        raise ValidationError(
            "At least one opt-in flag must be given explicitly."
        )

    changes = tuple(
        OptInChange(field, getattr(client, field), requested[field])
        for field in _FIELDS
        if requested[field] is not None
        and requested[field] != getattr(client, field)
    )
    if not changes:
        return OptInUpdate(
            client=client, salon=salon,
            sms_opt_in=client.sms_opt_in, email_opt_in=client.email_opt_in,
        )

    with transaction.atomic():
        for change in changes:
            setattr(client, change.field, change.new_value)
        client.save(update_fields=[change.field for change in changes])
    return OptInUpdate(
        client=client, salon=salon,
        sms_opt_in=client.sms_opt_in, email_opt_in=client.email_opt_in,
        changed_fields=tuple(change.field for change in changes),
        changes=changes,
        changed_at=timezone.now(),
    )
