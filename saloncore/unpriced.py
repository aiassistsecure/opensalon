"""Read-only unpriced-services report for the price book.

Pure service: nothing here creates, updates, or deletes any row, and
no price is ever invented. A service counts as priced for a level
only when it has an ``active`` :class:`~saloncore.models.ServicePrice`
row for that level — matching ``price_feed``, which only exposes
active prices as the current price book.

Salon scoping follows the real relations in ``saloncore.models``:
``Service.category`` -> ``ServiceCategory.salon``, and
``StaffLevel.salon``.
"""

from dataclasses import dataclass

from saloncore.models import Service, StaffLevel


@dataclass(frozen=True)
class MissingLevel:
    """A staff level that has no (active) price for a service."""

    level_id: int
    level_name: str

    def to_dict(self):
        return {"id": self.level_id, "name": self.level_name}


@dataclass(frozen=True)
class UnpricedService:
    """One active service with at least one missing price."""

    service_id: int
    service_name: str
    category_id: int
    category_name: str
    missing_levels: tuple = ()

    def to_dict(self):
        return {
            "service_id": self.service_id,
            "service_name": self.service_name,
            "category_id": self.category_id,
            "category_name": self.category_name,
            "missing_levels": [level.to_dict() for level in self.missing_levels],
            "missing_level_ids": [level.level_id for level in self.missing_levels],
        }


def _active_levels(salon):
    return list(
        StaffLevel.objects.filter(salon=salon, active=True).order_by(
            "sort_order", "name"
        )
    )


def _active_services(salon):
    return (
        Service.objects.filter(category__salon=salon, active=True)
        .select_related("category")
        .prefetch_related("prices")
        .order_by("category__sort_order", "category__name", "name")
    )


def _priced_level_ids(service):
    return {price.staff_level_id for price in service.prices.all() if price.active}


def _entry(service, levels, priced_ids):
    missing = tuple(
        MissingLevel(level_id=level.pk, level_name=level.name)
        for level in levels
        if level.pk not in priced_ids
    )
    return UnpricedService(
        service_id=service.pk,
        service_name=service.name,
        category_id=service.category_id,
        category_name=service.category.name,
        missing_levels=missing,
    )


def fully_unpriced_services(salon):
    """Active services in ``salon`` with no ServicePrice rows at all.

    More precisely, no *active* price rows: a service whose only
    prices are inactive is effectively unpriced in the price book.
    Each entry lists every active staff level as missing.
    """
    levels = _active_levels(salon)
    result = []
    for service in _active_services(salon):
        priced_ids = _priced_level_ids(service)
        if not priced_ids:
            result.append(_entry(service, levels, priced_ids))
    return result


def unpriced_services(salon, staff_level=None):
    """Return unpriced active services for ``salon`` as structured data.

    Without ``staff_level`` this is :func:`fully_unpriced_services`:
    services with no price rows at all. When a ``StaffLevel`` is
    passed, it returns every active service missing a price for that
    level (fully unpriced services included). Either way each entry
    carries the service id/name/category and *all* levels it lacks a
    price for, not just the level asked about.

    Raises ``ValueError`` if ``staff_level`` belongs to another salon.
    Read-only: this function never mutates any row.
    """
    if staff_level is None:
        return fully_unpriced_services(salon)
    if staff_level.salon_id != salon.pk:
        raise ValueError("staff_level does not belong to this salon")
    levels = _active_levels(salon)
    result = []
    for service in _active_services(salon):
        priced_ids = _priced_level_ids(service)
        if staff_level.pk not in priced_ids:
            result.append(_entry(service, levels, priced_ids))
    return result


# Friendly alias for callers that read better with a verb.
get_unpriced_services = unpriced_services


def price_book_completeness(salon, staff_level=None):
    """Structured completeness summary for a salon's price book.

    Returns a plain ``dict`` (JSON-friendly via ``to_dict`` entries)
    with the fully-unpriced list and, when ``staff_level`` is given,
    the list of services missing a price for that level.
    """
    fully = fully_unpriced_services(salon)
    report = {
        "salon_id": salon.pk,
        "salon_name": salon.name,
        "fully_unpriced": [entry.to_dict() for entry in fully],
        "fully_unpriced_count": len(fully),
        "staff_level_id": None,
        "missing_for_level": None,
        "missing_for_level_count": None,
    }
    if staff_level is not None:
        missing = unpriced_services(salon, staff_level=staff_level)
        report["staff_level_id"] = staff_level.pk
        report["missing_for_level"] = [entry.to_dict() for entry in missing]
        report["missing_for_level_count"] = len(missing)
    return report
