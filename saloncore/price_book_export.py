"""Full price book CSV export service.

Backend only -- no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a service, a category,
a staff level, or a price.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports a salon's full price
book as a plain, JSON-serializable list of dicts
(:func:`export_price_book`) and as a CSV string
(:func:`export_price_book_csv`) built from that same list, so
the two formats can never disagree -- one source of truth.

Rows are read verbatim from the stored ``Service`` /
``ServiceCategory`` / ``StaffLevel`` / ``ServicePrice``
records. No price is recomputed or invented. There is one row
per (service, staff level) price; a service with no price rows
at all still appears once, with the staff-level and price
columns empty (``None``), so an unpriced service is visible in
the export instead of silently missing from the book.

Columns are only real fields:

- ``salon_id``: the salon pk (via the service's category).
- ``category_id`` / ``category_name``: the service's category.
- ``service_id`` / ``service_name`` / ``description`` /
  ``external_id``: the service itself.
- ``service_minutes`` / ``processing_minutes`` /
  ``finishing_minutes`` / ``total_minutes``: the duration
  segments. ``processing_minutes`` is the gap / processing
  segment (the segment a previous system's ``gapTime`` maps
  to on import); ``total_minutes`` is their sum, exactly the
  ``Service.total_minutes`` property.
- ``service_active``: ``Service.active``, verbatim.
- ``staff_level_id`` / ``staff_level_name``: the price's
  staff level (empty for an unpriced service).
- ``service_price_id`` / ``amount`` / ``is_from`` /
  ``price_active``: the price itself (empty for an unpriced
  service). ``amount`` is formatted to two decimal places as
  a string, ``"85.00"``.
- ``payload``: the service's verbatim source record
  (``Service.payload``, TF-10), included ONLY when non-empty --
  as a dict key on the dict export, and as an extra CSV column
  (JSON string) on the CSV export when any service in the book
  carries one. ``import_price_book`` restores it as-is, so the
  payload round-trips unchanged; a book with no payloads
  exports exactly as before, with no ``payload`` key or column.

Nothing is filtered on ``active``: inactive categories,
services, levels, and prices are exported too, with their
``active`` state recorded verbatim, so the export is the
complete book a salon could take with it.

Salon isolation: only services whose category belongs to the
given salon are included, and only prices whose staff level
also belongs to that salon.

Ordering is deterministic: by category ``sort_order``, then
category name, then service name, then service ``id``; within
a service, by staff level ``sort_order``, then level name,
then price ``id``.
"""
import csv
import io
import json
from decimal import Decimal

from saloncore.models import Service

__all__ = [
    "EXPORT_FIELDNAMES",
    "PRICE_BOOK_EXPORT_FIELDNAMES",
    "PRICE_BOOK_FIELDNAMES",
    "export_price_book",
    "export_price_book_csv",
    "price_book_csv",
]

#: Column / key order shared by the dict export and the CSV export.
PRICE_BOOK_FIELDNAMES = [
    "salon_id",
    "category_id",
    "category_name",
    "service_id",
    "service_name",
    "description",
    "external_id",
    "service_minutes",
    "processing_minutes",
    "finishing_minutes",
    "total_minutes",
    "service_active",
    "staff_level_id",
    "staff_level_name",
    "service_price_id",
    "amount",
    "is_from",
    "price_active",
]
PRICE_BOOK_EXPORT_FIELDNAMES = PRICE_BOOK_FIELDNAMES
EXPORT_FIELDNAMES = PRICE_BOOK_FIELDNAMES

_ZERO = Decimal("0.00")


def _money(value):
    return str(Decimal(value).quantize(_ZERO)) if value is not None else None


def _base_record(salon_id, service):
    category = service.category
    record = {
        "salon_id": salon_id,
        "category_id": category.pk,
        "category_name": category.name,
        "service_id": service.pk,
        "service_name": service.name,
        "description": service.description,
        "external_id": service.external_id,
        "service_minutes": service.service_minutes,
        "processing_minutes": service.processing_minutes,
        "finishing_minutes": service.finishing_minutes,
        "total_minutes": service.total_minutes,
        "service_active": bool(service.active),
        "staff_level_id": None,
        "staff_level_name": None,
        "service_price_id": None,
        "amount": None,
        "is_from": None,
        "price_active": None,
    }
    payload = getattr(service, "payload", None)
    if payload:
        record["payload"] = payload
    return record


def _record(salon_id, service, price):
    record = _base_record(salon_id, service)
    if price is not None:
        level = price.staff_level
        record.update({
            "staff_level_id": level.pk,
            "staff_level_name": level.name,
            "service_price_id": price.pk,
            "amount": _money(price.amount),
            "is_from": bool(price.is_from),
            "price_active": bool(price.active),
        })
    return record


def export_price_book(salon):
    """Return ``salon``'s full price book as dicts.

    Each entry is a dict with exactly
    :data:`PRICE_BOOK_FIELDNAMES` keys, plus a ``payload``
    key when the service carries a verbatim source record.
    Only ``salon``'s services and prices are included, ordered
    as described in the module docstring. A salon with no
    services exports as ``[]``; ``salon=None`` exports as
    ``[]``. Read-only.
    """
    if salon is None:
        return []
    salon_id = getattr(salon, "pk", salon)
    services = (
        Service.objects.filter(category__salon_id=salon_id)
        .select_related("category")
        .prefetch_related("prices__staff_level")
        .order_by(
            "category__sort_order", "category__name", "name", "id")
    )
    records = []
    for service in services:
        prices = sorted(
            (p for p in service.prices.all()
             if p.staff_level.salon_id == salon_id),
            key=lambda p: (
                p.staff_level.sort_order, p.staff_level.name, p.pk),
        )
        if not prices:
            records.append(_record(salon_id, service, None))
        for price in prices:
            records.append(_record(salon_id, service, price))
    return records


def export_price_book_csv(salon):
    """Return ``salon``'s full price book as CSV.

    The header row is :data:`PRICE_BOOK_FIELDNAMES` and every
    data row comes from :func:`export_price_book` with the
    same argument, so the CSV and list exports always agree.
    When any exported service carries a payload, a trailing
    ``payload`` column is added holding it as a JSON string
    (empty on rows whose service has none); a payload-free
    book's CSV is byte-identical to the export before TF-10.
    A salon with no services exports as the header row alone.
    Lines end ``"\\n"``.
    """
    records = export_price_book(salon)
    fieldnames = list(PRICE_BOOK_FIELDNAMES)
    if any("payload" in record for record in records):
        fieldnames.append("payload")
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=fieldnames, lineterminator="\n"
    )
    writer.writeheader()
    for record in records:
        row = dict(record)
        if "payload" in row:
            row["payload"] = json.dumps(row["payload"], sort_keys=True)
        writer.writerow(row)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
price_book_csv = export_price_book_csv
