"""Single-service update service for the price book.

Backend only -- no views, templates, or UI.

The validated partial-update write path for an existing
``Service``: every field is optional, ``None`` (the default)
means "leave unchanged", and only the fields given are cleaned
and written. Updatable: ``name``, ``description``, ``category``
(an instance, an id, or ``category_name`` resolved inside the
salon), the three duration segments (``service_minutes``,
``processing_minutes``, ``finishing_minutes``), and ``active``.

All validation reuses :mod:`saloncore.add_service`'s cleaners
verbatim, so creating and updating a service can never disagree:
name non-blank within the model limit, description a string,
minute segments whole non-negative integers (hands-on at
least 1), ``active`` a bool, category resolution exactly as
``add_service`` resolves it. Calling with no field at all is
refused -- there is no silent no-op update.

Pricing is NOT this module's job: ``saloncore.pricing.set_price``
owns prices, and an update here never touches them.
"""
from django.db import transaction

from saloncore.add_service import (
    _clean_active,
    _clean_category,
    _clean_description,
    _clean_minutes,
    _clean_name,
    _clean_salon,
)
from saloncore.models import Service

__all__ = ["update_service", "validate_update_service"]


def _clean_service(salon, service):
    if not isinstance(service, Service) or service.pk is None:
        raise ValueError("service must be a saved Service instance")
    if service.category.salon_id != salon.pk:
        raise ValueError("service belongs to a different salon")
    return service


def validate_update_service(salon, service, name=None, description=None,
                            category=None, category_name=None,
                            service_minutes=None, processing_minutes=None,
                            finishing_minutes=None, active=None):
    """Validate an ``update_service`` call, writing nothing.

    Performs every check :func:`update_service` performs, returns
    a dict of the cleaned fields that WOULD be stored (only the
    fields given -- omitted fields are absent), raises the same
    ``ValueError``, and writes nothing -- safe for ``--dry-run``
    on every backend (NEDB included: no rollback is relied on).
    """
    salon = _clean_salon(salon)
    _clean_service(salon, service)
    cleaned = {}
    if category is not None or category_name not in (None, ""):
        cleaned["category"] = _clean_category(salon, category, category_name)
    if name is not None:
        cleaned["name"] = _clean_name(name)
    if description is not None:
        cleaned["description"] = _clean_description(description)
    if service_minutes is not None:
        cleaned["service_minutes"] = _clean_minutes(
            service_minutes, "service_minutes", 1)
    if processing_minutes is not None:
        cleaned["processing_minutes"] = _clean_minutes(
            processing_minutes, "processing_minutes", 0)
    if finishing_minutes is not None:
        cleaned["finishing_minutes"] = _clean_minutes(
            finishing_minutes, "finishing_minutes", 0)
    if active is not None:
        cleaned["active"] = _clean_active(active)
    if not cleaned:
        raise ValueError("at least one field must be given to update")
    return cleaned


def update_service(salon, service, name=None, description=None,
                   category=None, category_name=None,
                   service_minutes=None, processing_minutes=None,
                   finishing_minutes=None, active=None):
    """Update the given fields of ``service`` in ``salon``; return it.

    Only fields passed as non-``None`` change; prices are never
    touched (``set_price`` owns them). Raises ``ValueError`` --
    writing nothing -- for an unsaved or cross-salon salon or
    service, no field given, a missing/unknown/cross-salon/
    ambiguous category, a blank/over-long name, a non-string
    description, a non-whole or negative minute segment,
    hands-on under 1, or a non-bool ``active``.
    """
    with transaction.atomic():
        cleaned = validate_update_service(
            salon, service, name=name, description=description,
            category=category, category_name=category_name,
            service_minutes=service_minutes,
            processing_minutes=processing_minutes,
            finishing_minutes=finishing_minutes, active=active)
        for field, value in cleaned.items():
            setattr(service, field, value)
        service.save(update_fields=list(cleaned))
        return service
