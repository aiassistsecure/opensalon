"""Price-book structure CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a category or a level.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports a salon's price-book
structure records -- :class:`~saloncore.models.ServiceCategory`
and :class:`~saloncore.models.StaffLevel` -- verbatim, as plain
JSON-serializable lists of dicts and as CSV strings built from
those same lists, so the two formats can never disagree -- one
source of truth.

Why these records need their own surface: everywhere else in
saloncore a category or level appears only as an id/name column
inside a service-driven price book row, so ``sort_order`` and
``active`` render nowhere standalone, and a category with no
services (or a level with no prices) is invisible outside the
salon_data bundle. Here every stored row renders, used or not.

Columns are only real fields: the row's ``id``, its ``salon_id``,
``name``, ``sort_order`` and ``active`` -- identical shape for
both record kinds. No fields are invented and nothing is derived
from services or prices.

Salon isolation: only rows whose ``salon`` is the given salon are
included. Ordering follows each model's own ordering
(``sort_order``, then ``name``), tightened with an ``id``
tie-break. A salon with no rows of a kind exports that kind as
``[]`` / the header row alone. Lines end ``"\\n"``.
"""
import csv
import io

from saloncore.models import ServiceCategory, StaffLevel

__all__ = [
    "SERVICE_CATEGORY_FIELDNAMES",
    "STAFF_LEVEL_FIELDNAMES",
    "export_service_categories",
    "export_service_categories_csv",
    "service_categories_csv",
    "export_staff_levels",
    "export_staff_levels_csv",
    "staff_levels_csv",
    "export_structure",
    "export_structure_csv",
    "structure_csv",
]

#: Column / key order for a ServiceCategory row, shared by the
#: dict export and the CSV export.
SERVICE_CATEGORY_FIELDNAMES = [
    "id",
    "salon_id",
    "name",
    "sort_order",
    "active",
]

#: Column / key order for a StaffLevel row -- the same stored
#: shape as a category row.
STAFF_LEVEL_FIELDNAMES = [
    "id",
    "salon_id",
    "name",
    "sort_order",
    "active",
]


def _record(row):
    return {
        "id": row.pk,
        "salon_id": row.salon_id,
        "name": row.name,
        "sort_order": row.sort_order,
        "active": bool(row.active),
    }


def _csv(rows, fieldnames):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for record in rows:
        writer.writerow(record)
    return buffer.getvalue()


def export_service_categories(salon):
    """Return ``salon``'s service categories verbatim as dicts.

    Each entry is a dict with exactly
    :data:`SERVICE_CATEGORY_FIELDNAMES` keys, ordered by
    (``sort_order``, ``name``, ``id``). Categories with no
    services are included. A salon with no categories exports
    as ``[]``. Read-only.
    """
    queryset = (
        ServiceCategory.objects.filter(salon=salon)
        .order_by("sort_order", "name", "id")
    )
    return [_record(row) for row in queryset]


def export_service_categories_csv(salon):
    """Return ``salon``'s service categories as CSV.

    The header row is :data:`SERVICE_CATEGORY_FIELDNAMES` and
    every data row comes from :func:`export_service_categories`,
    so the CSV and list exports always agree.
    """
    return _csv(export_service_categories(salon), SERVICE_CATEGORY_FIELDNAMES)


#: Alias, mirroring the naming convenience in sibling services.
service_categories_csv = export_service_categories_csv


def export_staff_levels(salon):
    """Return ``salon``'s staff levels verbatim as dicts.

    Each entry is a dict with exactly
    :data:`STAFF_LEVEL_FIELDNAMES` keys, ordered by
    (``sort_order``, ``name``, ``id``). Levels with no prices
    are included. A salon with no levels exports as ``[]``.
    Read-only.
    """
    queryset = (
        StaffLevel.objects.filter(salon=salon)
        .order_by("sort_order", "name", "id")
    )
    return [_record(row) for row in queryset]


def export_staff_levels_csv(salon):
    """Return ``salon``'s staff levels as CSV.

    The header row is :data:`STAFF_LEVEL_FIELDNAMES` and every
    data row comes from :func:`export_staff_levels`, so the CSV
    and list exports always agree.
    """
    return _csv(export_staff_levels(salon), STAFF_LEVEL_FIELDNAMES)


#: Alias, mirroring the naming convenience in sibling services.
staff_levels_csv = export_staff_levels_csv


def export_structure(salon):
    """Return ``salon``'s whole price-book structure as dicts.

    ``{"service_categories": [...], "staff_levels": [...]}``,
    each list exactly the corresponding single-kind export above.
    Read-only.
    """
    return {
        "service_categories": export_service_categories(salon),
        "staff_levels": export_staff_levels(salon),
    }


def export_structure_csv(salon):
    """Return ``salon``'s whole price-book structure as CSV text.

    The service-categories CSV block followed by one blank line
    and the staff-levels CSV block; each block is exactly the
    corresponding single-kind CSV export above, header included,
    so the combined text can never disagree with them.
    """
    return (
        export_service_categories_csv(salon)
        + "\n"
        + export_staff_levels_csv(salon)
    )


#: Alias, mirroring the naming convenience in sibling services.
structure_csv = export_structure_csv
