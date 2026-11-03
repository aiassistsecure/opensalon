"""Single-service creation service for the price book.

Backend only -- no views, templates, or UI.

Today ``Service`` rows arrive only via bulk import
(``import_price_book`` / ``import_salon_data``). This module is
the validated single-record write path: it creates exactly one
service in one salon, under one of that salon's categories, from
its name, description, and the three duration segments on the
model (hands-on ``service_minutes``, ``processing_minutes``,
``finishing_minutes``).

Pricing is NOT this module's job: ``saloncore.pricing.set_price``
prices an existing service at an existing level, and stays the
single source of truth for prices. A service created here has no
prices until ``set_price`` is called on it.

Category resolution lives here: a category may be a saved
``ServiceCategory``, an id, or ``category_name`` -- resolved
inside the salon (exact stripped match; no match or more than
one is refused). Exactly one form, belonging to the salon.
No uniqueness rule on service names (the model carries none;
imports key on ``external_id``, blank here), so duplicates
are not refused.

Validation mirrors add_product: name non-blank within the
model limit, description a string (blank default), minute
segments whole non-negative integers (hands-on at least 1),
``active`` a bool.
"""
from django.db import transaction

from saloncore.models import Salon, Service, ServiceCategory

__all__ = ["add_service", "validate_add_service"]

_NAME_LIMIT = Service._meta.get_field("name").max_length
_CATEGORY_NAME_LIMIT = ServiceCategory._meta.get_field("name").max_length


def _clean_salon(salon):
    if not isinstance(salon, Salon) or salon.pk is None:
        raise ValueError("salon must be a saved Salon instance")
    return salon


def _clean_category(salon, category, category_name):
    if category is not None and category_name not in (None, ""):
        raise ValueError("pass either category or category_name, not both")
    if category_name not in (None, ""):
        if not isinstance(category_name, str) or not category_name.strip():
            raise ValueError("category_name must not be blank")
        text = category_name.strip()
        if len(text) > _CATEGORY_NAME_LIMIT:
            raise ValueError(
                f"category_name exceeds {_CATEGORY_NAME_LIMIT} characters")
        matches = list(ServiceCategory.objects.filter(salon=salon, name=text))
        if not matches:
            raise ValueError(
                f"no category named {text!r} in salon {salon.pk}")
        if len(matches) > 1:
            raise ValueError(
                f"category name {text!r} is ambiguous in salon {salon.pk}; "
                "pass the category id")
        return matches[0]
    if category is None:
        raise ValueError("a category is required")
    if isinstance(category, bool):
        raise ValueError("category must be a category or its id")
    if isinstance(category, int):
        try:
            category = ServiceCategory.objects.get(pk=category)
        except ServiceCategory.DoesNotExist:
            raise ValueError(f"no category with id {category}") from None
    if not isinstance(category, ServiceCategory) or category.pk is None:
        raise ValueError("category must be a saved ServiceCategory instance")
    if category.salon_id != salon.pk:
        raise ValueError("category belongs to a different salon")
    return category


def _clean_name(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("service name must not be blank")
    text = name.strip()
    if len(text) > _NAME_LIMIT:
        raise ValueError(f"service name exceeds {_NAME_LIMIT} characters")
    return text


def _clean_description(description):
    if description is None:
        return ""
    if not isinstance(description, str):
        raise ValueError("description must be a string")
    return description


def _clean_minutes(value, field, minimum):
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field} is required")
    if isinstance(value, str):
        text = value.strip()
        if not text.lstrip("+-").isdigit():
            raise ValueError(f"{field} must be a whole number of minutes")
        value = int(text)
    if not isinstance(value, int):
        raise ValueError(f"{field} must be a whole number of minutes")
    if value < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return value


def _clean_active(active):
    if not isinstance(active, bool):
        raise ValueError("active must be a boolean")
    return active


def validate_add_service(salon, name, service_minutes, category=None,
                         category_name=None, description="",
                         processing_minutes=0, finishing_minutes=0,
                         active=True):
    """Validate an ``add_service`` call, writing nothing.

    Performs every check :func:`add_service` performs, returns the
    cleaned fields the writer would store, raises the same
    ``ValueError``, and writes nothing -- safe for ``--dry-run``
    on every backend (NEDB included: no rollback is relied on).
    """
    salon = _clean_salon(salon)
    return dict(
        category=_clean_category(salon, category, category_name),
        name=_clean_name(name),
        description=_clean_description(description),
        service_minutes=_clean_minutes(service_minutes, "service_minutes", 1),
        processing_minutes=_clean_minutes(
            processing_minutes, "processing_minutes", 0),
        finishing_minutes=_clean_minutes(
            finishing_minutes, "finishing_minutes", 0),
        active=_clean_active(active))


def add_service(salon, name, service_minutes, category=None,
                category_name=None, description="", processing_minutes=0,
                finishing_minutes=0, active=True):
    """Create one service in ``salon`` and return it.

    Created with no prices (pricing is ``set_price``'s job).
    Raises ``ValueError`` -- creating nothing -- for an unsaved
    salon, a missing/unknown/cross-salon/ambiguous category, a
    blank/over-long name, a non-string description, a non-whole
    or negative minute segment, hands-on under 1, or non-bool
    ``active``.
    """
    with transaction.atomic():
        cleaned = validate_add_service(
            salon, name, service_minutes, category=category,
            category_name=category_name, description=description,
            processing_minutes=processing_minutes,
            finishing_minutes=finishing_minutes, active=active)
        return Service.objects.create(**cleaned)
