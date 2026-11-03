"""Single-staff-member creation service for the team app.

Backend only -- no views, templates, or UI. Today
``StaffMember`` rows arrive only via bulk import
(``import_staff``) or a webui ``objects.create`` that
re-implements level/PIN/email handling in the view. This is
the validated single-record write path: one member in one
salon from a display name, an optional staff level, the
per-staff online-booking toggle, and optional email / PIN.

Rules (this service is the single source of truth): the
name is non-blank, at most the field length, stored stripped
(never truncated); a given ``staff_level`` must be saved and
belong to the SAME salon (cross-salon refused);
``online_bookable`` must be a real boolean; a non-blank
``email`` must be valid and not already name another ACTIVE
member's account (case-insensitive -- sign-in is email+PIN,
as in webui); a non-blank ``pin`` must be 4 to 8 digits (the
webui rule) and unique within the salon, matching the
model's ``uniq_staff_pin_per_salon`` constraint (same PIN in
another salon is fine; blank PIN/email are exempt).
Capabilities and roster stay the existing ``set_*``
services'/commands' job, untouched.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember

__all__ = ["add_staff_member", "validate_add_staff_member"]

_NAME_LIMIT = StaffMember._meta.get_field("display_name").max_length
_PIN_LIMIT = StaffMember._meta.get_field("pin").max_length
_EMAIL_LIMIT = StaffMember._meta.get_field("email").max_length


def _clean_salon(salon):
    if not isinstance(salon, Salon) or salon.pk is None:
        raise ValueError("salon must be a saved Salon instance")
    return salon


def _clean_display_name(display_name):
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError("display_name must not be blank")
    text = display_name.strip()
    if len(text) > _NAME_LIMIT:
        raise ValueError(
            f"display_name exceeds {_NAME_LIMIT} characters")
    return text


def _clean_staff_level(salon, staff_level):
    if staff_level is None:
        return None
    if not isinstance(staff_level, StaffLevel) or staff_level.pk is None:
        raise ValueError("staff_level must be a saved StaffLevel instance")
    if staff_level.salon_id != salon.pk:
        raise ValueError(
            f"staff_level {staff_level.pk} does not belong to "
            f"salon {salon.pk}")
    return staff_level


def _clean_email(salon, email):
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
            email="").exists():
        raise ValueError(
            f"email {text!r} is already used by another staff member")
    return text


def _clean_pin(salon, pin):
    if pin is None:
        return ""
    if isinstance(pin, bool) or not isinstance(pin, (str, int)):
        raise ValueError("pin must be a string of digits")
    text = str(pin).strip()
    if not text:
        return ""
    if not text.isdigit() or not 4 <= len(text) <= _PIN_LIMIT:
        raise ValueError(f"pin must be 4 to {_PIN_LIMIT} digits")
    if StaffMember.objects.filter(salon=salon, pin=text).exists():
        raise ValueError(
            f"pin is already used by another staff member in "
            f"salon {salon.pk}")
    return text


def validate_add_staff_member(salon, display_name, staff_level=None,
                              online_bookable=True, email="", pin=""):
    """Validate an ``add_staff_member`` call, writing nothing.

    Returns the cleaned fields the writer would store (keys
    ``salon``, ``display_name``, ``staff_level``,
    ``online_bookable``, ``email``, ``pin``) and raises the
    same ``ValueError`` the writer would. Safe for ``--dry-run``
    on every backend (including NEDB, where a rolled-back
    transaction does not undo writes).
    """
    salon = _clean_salon(salon)
    if not isinstance(online_bookable, bool):
        raise ValueError("online_bookable must be a boolean")
    return dict(
        salon=salon, display_name=_clean_display_name(display_name),
        staff_level=_clean_staff_level(salon, staff_level),
        online_bookable=online_bookable,
        email=_clean_email(salon, email), pin=_clean_pin(salon, pin))


def add_staff_member(salon, display_name, staff_level=None,
                     online_bookable=True, email="", pin=""):
    """Create one staff member in ``salon`` and return it.
    Raises ``ValueError`` -- creating nothing -- on any rule
    in the module docstring."""
    with transaction.atomic():
        cleaned = validate_add_staff_member(
            salon, display_name, staff_level=staff_level,
            online_bookable=online_bookable, email=email, pin=pin)
        return StaffMember.objects.create(**cleaned)
