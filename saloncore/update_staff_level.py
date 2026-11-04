"""Single staff-level update service for the price book.

Backend only -- no views, templates, or UI.

The validated partial-update write path for an existing
``StaffLevel``: every field is optional, ``None`` (the default)
means "leave unchanged", and only the fields given are cleaned
and written. Updatable: ``name``, ``sort_order`` and ``active``.

All validation reuses :mod:`saloncore.add_staff_level`'s cleaners
verbatim, so creating and updating a staff level can never
disagree: name non-blank within the model limit, ``sort_order``
a whole non-negative integer, ``active`` a bool. No uniqueness
rule on level names (the model carries none), so an update to a
name another level already carries is not refused either.
Calling with no field at all is refused -- there is no silent
no-op update.
"""
from django.db import transaction

from saloncore.add_staff_level import (
    _clean_active,
    _clean_name,
    _clean_salon,
    _clean_sort_order,
)
from saloncore.models import StaffLevel

__all__ = ["update_staff_level", "validate_update_staff_level"]


def _clean_staff_level(salon, staff_level):
    if not isinstance(staff_level, StaffLevel) or staff_level.pk is None:
        raise ValueError("staff_level must be a saved StaffLevel instance")
    if staff_level.salon_id != salon.pk:
        raise ValueError("staff level belongs to a different salon")
    return staff_level


def validate_update_staff_level(salon, staff_level, name=None,
                                sort_order=None, active=None):
    """Validate an ``update_staff_level`` call, writing nothing.

    Performs every check :func:`update_staff_level` performs,
    returns a dict of the cleaned fields that WOULD be stored
    (only the fields given -- omitted fields are absent), raises
    the same ``ValueError``, and writes nothing -- safe for
    ``--dry-run`` on every backend (NEDB included: no rollback
    is relied on).
    """
    salon = _clean_salon(salon)
    _clean_staff_level(salon, staff_level)
    cleaned = {}
    if name is not None:
        cleaned["name"] = _clean_name(name)
    if sort_order is not None:
        cleaned["sort_order"] = _clean_sort_order(sort_order)
    if active is not None:
        cleaned["active"] = _clean_active(active)
    if not cleaned:
        raise ValueError("at least one field must be given to update")
    return cleaned


def update_staff_level(salon, staff_level, name=None, sort_order=None,
                       active=None):
    """Update the given fields of ``staff_level`` in ``salon``.

    Only fields passed as non-``None`` change; returns the level.
    Raises ``ValueError`` -- writing nothing -- for an unsaved or
    cross-salon salon or staff level, no field given, a blank or
    over-long name, a non-whole or negative ``sort_order``, or a
    non-bool ``active``.
    """
    with transaction.atomic():
        cleaned = validate_update_staff_level(
            salon, staff_level, name=name, sort_order=sort_order,
            active=active)
        for field, value in cleaned.items():
            setattr(staff_level, field, value)
        staff_level.save(update_fields=list(cleaned))
        return staff_level
