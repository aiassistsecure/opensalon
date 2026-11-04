"""Single service-category update service for the price book.

Backend only -- no views, templates, or UI.

The validated partial-update write path for an existing
``ServiceCategory``: every field is optional, ``None`` (the
default) means "leave unchanged", and only the fields given
are cleaned and written. Updatable: ``name``, ``sort_order``
and ``active``.

All validation reuses :mod:`saloncore.add_service_category`'s
cleaners verbatim, so creating and updating a service category
can never disagree: name non-blank within the model limit,
``sort_order`` a whole non-negative integer, ``active`` a
bool. No uniqueness rule on category names (the model carries
none), so an update to a name another category already carries
is not refused either. Calling with no field at all is
refused -- there is no silent no-op update.
"""
from django.db import transaction

from saloncore.add_service_category import (
    _clean_active,
    _clean_name,
    _clean_salon,
    _clean_sort_order,
)
from saloncore.models import ServiceCategory

__all__ = ["update_service_category", "validate_update_service_category"]


def _clean_service_category(salon, service_category):
    if not isinstance(service_category, ServiceCategory) \
            or service_category.pk is None:
        raise ValueError(
            "service_category must be a saved ServiceCategory instance")
    if service_category.salon_id != salon.pk:
        raise ValueError("service category belongs to a different salon")
    return service_category


def validate_update_service_category(salon, service_category, name=None,
                                     sort_order=None, active=None):
    """Validate an ``update_service_category`` call, writing nothing.

    Performs every check :func:`update_service_category` performs,
    returns a dict of the cleaned fields that WOULD be stored
    (only the fields given -- omitted fields are absent), raises
    the same ``ValueError``, and writes nothing -- safe for
    ``--dry-run`` on every backend (NEDB included: no rollback
    is relied on).
    """
    salon = _clean_salon(salon)
    _clean_service_category(salon, service_category)
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


def update_service_category(salon, service_category, name=None,
                            sort_order=None, active=None):
    """Update the given fields of ``service_category`` in ``salon``.

    Only fields passed as non-``None`` change; returns the category.
    Raises ``ValueError`` -- writing nothing -- for an unsaved or
    cross-salon salon or service category, no field given, a blank
    or over-long name, a non-whole or negative ``sort_order``, or a
    non-bool ``active``.
    """
    with transaction.atomic():
        cleaned = validate_update_service_category(
            salon, service_category, name=name, sort_order=sort_order,
            active=active)
        for field, value in cleaned.items():
            setattr(service_category, field, value)
        service_category.save(update_fields=list(cleaned))
        return service_category
