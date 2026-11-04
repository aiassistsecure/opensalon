"""Single-staff-member update service for the team app.

Backend only -- no views, templates, or UI. The validated
write path for editing an existing ``StaffMember``: every
field is optional, ``None`` (the default) means "leave
unchanged", and only fields whose cleaned value actually
differs are written, via ``save(update_fields=[...])`` --
the shape of ``clients.optins.update_client_opt_ins``.

Rules (this service is the single source of truth): the
member must be saved and belong to the given salon; at
least one field must be given (no silent no-op update);
``online_bookable`` / ``active`` must be real booleans.
Field cleaning reuses ``team.add_staff_member``'s cleaners
verbatim -- display name non-blank / stripped / at most the
field length, staff level saved and same-salon, email valid
and not another ACTIVE member's (case-insensitive), PIN 4
to 8 digits and unique within the salon -- with the one
adaptation an update requires: the member being updated is
excluded from the email/PIN uniqueness checks, so keeping
its own current email/PIN is not a self-collision. A blank
email/PIN string clears that field. Capabilities and
roster stay the ``set_*`` services'/commands' job.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction

from saloncore.models import Salon
from team.add_staff_member import (
    _EMAIL_LIMIT, _PIN_LIMIT, _clean_display_name, _clean_salon,
    _clean_staff_level)
from team.models import StaffMember

__all__ = ["update_staff_member", "validate_update_staff_member"]

_FIELDS = ("display_name", "staff_level", "email", "pin",
           "online_bookable", "active")


def _clean_email(member, email):
    # add_staff_member._clean_email verbatim, except the
    # uniqueness query excludes the member being updated.
    if email is None:
        return ""
    if not isinstance(email, str):
        raise ValueError("email must be a string")
    text = email.strip()
    if not text:
        return ""
    if len(text) > _EMAIL_LIMIT:
        raise ValueError(f"email exceeds {_EMAIL_LIMIT} characters")
    try:
        validate_email(text)
    except DjangoValidationError:
        raise ValueError(f"email {text!r} is not a valid address") from None
    if StaffMember.objects.filter(
            email__iexact=text, active=True).exclude(
            email="").exclude(pk=member.pk).exists():
        raise ValueError(
            f"email {text!r} is already used by another staff member")
    return text


def _clean_pin(member, pin):
    # add_staff_member._clean_pin verbatim, except the
    # uniqueness query excludes the member being updated.
    if pin is None:
        return ""
    if isinstance(pin, bool) or not isinstance(pin, (str, int)):
        raise ValueError("pin must be a string of digits")
    text = str(pin).strip()
    if not text:
        return ""
    if not text.isdigit() or not 4 <= len(text) <= _PIN_LIMIT:
        raise ValueError(f"pin must be 4 to {_PIN_LIMIT} digits")
    if StaffMember.objects.filter(
            salon_id=member.salon_id, pin=text).exclude(
            pk=member.pk).exists():
        raise ValueError(
            f"pin is already used by another staff member in "
            f"salon {member.salon_id}")
    return text


def _clean_bool(name, value):
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def validate_update_staff_member(salon, member, *,
                                 display_name=None, staff_level=None,
                                 email=None, pin=None,
                                 online_bookable=None, active=None):
    """Validate an ``update_staff_member`` call, writing nothing.

    Returns the cleaned fields the writer would store, keyed
    by field name, for the fields given only. Raises the same
    ``ValueError`` the writer would. Safe for ``--dry-run``
    on every backend (including NEDB, where a rolled-back
    transaction does not undo writes).
    """
    salon = _clean_salon(salon)
    if not isinstance(member, StaffMember) or member.pk is None:
        raise ValueError("member must be a saved StaffMember instance")
    if member.salon_id != salon.pk:
        raise ValueError(
            f"member {member.pk} does not belong to salon {salon.pk}")
    given = dict(display_name=display_name, staff_level=staff_level,
                 email=email, pin=pin, online_bookable=online_bookable,
                 active=active)
    if all(value is None for value in given.values()):
        raise ValueError("at least one field must be given to update")
    cleaned = {}
    if display_name is not None:
        cleaned["display_name"] = _clean_display_name(display_name)
    if staff_level is not None:
        cleaned["staff_level"] = _clean_staff_level(salon, staff_level)
    if email is not None:
        cleaned["email"] = _clean_email(member, email)
    if pin is not None:
        cleaned["pin"] = _clean_pin(member, pin)
    if online_bookable is not None:
        cleaned["online_bookable"] = _clean_bool(
            "online_bookable", online_bookable)
    if active is not None:
        cleaned["active"] = _clean_bool("active", active)
    return cleaned


def update_staff_member(salon, member, **kwargs):
    """Apply the given field updates to ``member`` and return it.

    Only fields whose cleaned value differs are written.
    Raises ``ValueError`` -- writing nothing -- on any rule
    in the module docstring.
    """
    with transaction.atomic():
        cleaned = validate_update_staff_member(salon, member, **kwargs)
        changed = [field for field in _FIELDS
                   if field in cleaned
                   and getattr(member, field) != cleaned[field]]
        if changed:
            for field in changed:
                setattr(member, field, cleaned[field])
            member.save(update_fields=changed)
        return member
