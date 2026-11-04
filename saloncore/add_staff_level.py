"""Single staff-level creation service for the price book.

Backend only -- no views, templates, or UI.

Today ``StaffLevel`` rows arrive only via bulk import
(``import_salon_data``). This module is the validated
single-record write path: it creates exactly one staff level
in one salon, from its name, ``sort_order`` and ``active``
flag -- the model's real fields.

No uniqueness rule on level names (the model carries none),
so duplicates are not refused.

Validation mirrors add_service: salon must be a saved
``Salon``, name non-blank within the model limit,
``sort_order`` a whole non-negative integer, ``active``
a bool. Defaults match the model: ``sort_order`` 0,
``active`` True (creation-time active parity).
"""
from django.db import transaction

from saloncore.models import Salon, StaffLevel

__all__ = ["add_staff_level", "validate_add_staff_level"]

_NAME_LIMIT = StaffLevel._meta.get_field("name").max_length


def _clean_salon(salon):
    if not isinstance(salon, Salon) or salon.pk is None:
        raise ValueError("salon must be a saved Salon instance")
    return salon


def _clean_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("staff level name must not be blank")
    text = name.strip()
    if len(text) > _NAME_LIMIT:
        raise ValueError(f"staff level name exceeds {_NAME_LIMIT} characters")
    return text


def _clean_sort_order(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("sort_order is required")
    if isinstance(value, str):
        text = value.strip()
        if not text.lstrip("+-").isdigit():
            raise ValueError("sort_order must be a whole number")
        value = int(text)
    if not isinstance(value, int):
        raise ValueError("sort_order must be a whole number")
    if value < 0:
        raise ValueError("sort_order must be at least 0")
    return value


def _clean_active(active):
    if not isinstance(active, bool):
        raise ValueError("active must be a boolean")
    return active


def validate_add_staff_level(salon, name, sort_order=0, active=True):
    """Validate an ``add_staff_level`` call, writing nothing.

    Performs every check :func:`add_staff_level` performs,
    returns the cleaned fields the writer would store, raises
    the same ``ValueError``, and writes nothing -- safe for
    ``--dry-run`` on every backend (NEDB included).
    """
    salon = _clean_salon(salon)
    return dict(
        salon=salon,
        name=_clean_name(name),
        sort_order=_clean_sort_order(sort_order),
        active=_clean_active(active))


def add_staff_level(salon, name, sort_order=0, active=True):
    """Create one staff level in ``salon`` and return it.

    Raises ``ValueError`` -- creating nothing -- for an
    unsaved salon, a blank/over-long name, a non-whole or
    negative ``sort_order``, or non-bool ``active``.
    """
    with transaction.atomic():
        cleaned = validate_add_staff_level(
            salon, name, sort_order=sort_order, active=active)
        return StaffLevel.objects.create(**cleaned)
