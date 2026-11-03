"""Product export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a product or a stock movement.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's products as a plain,
JSON-serializable list (:func:`export_products`) and as a CSV
string (:func:`export_products_csv`) built from that same list, so
the two formats can never disagree — one source of truth.

Fields per product: ``id``, ``salon_id``, ``name``, ``sku``,
``barcode``, ``price``, ``active``, ``stock_on_hand``, and the
stored verbatim fields ``brand_name``, ``category_name``,
``product_type``, ``cost_price``, ``external_id``, and ``payload``
— rendered exactly as stored, never derived. ``price`` and
``cost_price`` are strings formatted to two decimal places (e.g.
``"24.00"``) because ``Decimal`` is not JSON-serializable; no money
value is ever passed through a float. ``cost_price`` is nullable:
a product with no cost recorded exports ``None`` (an empty CSV
cell), never zero. ``payload`` is the stored JSON document,
verbatim in the list export and JSON-encoded into its cell in
the CSV export (the ``export_all`` convention), so no part of
it is dropped or reshaped.

Stock is derived, never stored, and is NOT recomputed here: active
products take their on-hand quantity from
:func:`catalog.valuation.stock_valuation` (the movement-ledger
``SUM`` annotated query, the catalog's existing valuation helper),
and — only when ``include_inactive=True`` — inactive products take
theirs from ``Product.current_stock`` (the model's existing
ledger-derived property). A product with no movements exports
``stock_on_hand`` 0; a negative ledger balance is reported as it
stands, never clamped.

Active / inactive: by default only active products are exported,
matching ``stock_valuation`` and the stocktake sheet. Pass
``include_inactive=True`` for a complete exit export including
inactive products (their ``active`` field reads ``False``).

Ordering is deterministic: by product name, then id.
"""
import csv
import io
import json
from decimal import Decimal

from catalog.models import Product
from catalog.valuation import stock_valuation

__all__ = [
    "EXPORT_FIELDNAMES",
    "export_products",
    "export_products_csv",
    "export_catalog",
    "products_csv",
]

#: Column / key order shared by the dict export and the CSV export.
EXPORT_FIELDNAMES = [
    "id",
    "salon_id",
    "name",
    "sku",
    "barcode",
    "price",
    "active",
    "stock_on_hand",
    "brand_name",
    "category_name",
    "product_type",
    "cost_price",
    "external_id",
    "payload",
]

_ZERO = Decimal("0.00")


def _money(value):
    return str(Decimal(value).quantize(_ZERO))


def _record(product, on_hand):
    return {
        "id": product.pk,
        "salon_id": product.salon_id,
        "name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "price": _money(product.price),
        "active": bool(product.active),
        "stock_on_hand": int(on_hand),
        "brand_name": product.brand_name,
        "category_name": product.category_name,
        "product_type": product.product_type,
        "cost_price": (
            _money(product.cost_price)
            if product.cost_price is not None else None
        ),
        "external_id": product.external_id,
        "payload": product.payload if product.payload is not None else {},
    }


def export_products(salon, include_inactive=False):
    """Return ``salon``'s products as a JSON-serializable list.

    Each entry is a dict with exactly :data:`EXPORT_FIELDNAMES`
    keys (see the module docstring). Only ``salon``'s products are
    included. Inactive products are excluded unless
    ``include_inactive=True``. Ordered by name, then id.
    An empty catalog exports as ``[]``.
    """
    records = [
        _record(row.product, row.on_hand)
        for row in stock_valuation(salon).rows
    ]
    if include_inactive:
        salon_id = getattr(salon, "pk", salon)
        inactive = Product.objects.filter(
            salon_id=salon_id, active=False
        ).order_by("name", "id")
        records.extend(
            _record(product, product.current_stock) for product in inactive
        )
        records.sort(key=lambda r: (r["name"], r["id"]))
    else:
        # stock_valuation orders by value; the export contract is
        # name/id, so re-sort the (already fetched) records only.
        records.sort(key=lambda r: (r["name"], r["id"]))
    return records


def export_products_csv(salon, include_inactive=False):
    """Return ``salon``'s products as a CSV string.

    The header row is :data:`EXPORT_FIELDNAMES` and every data row
    comes from :func:`export_products` with the same arguments, so
    the CSV and list exports always agree. An empty catalog exports
    as the header row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_products(salon, include_inactive=include_inactive):
        row = dict(record)
        if isinstance(row["payload"], (dict, list)):
            row["payload"] = json.dumps(row["payload"], sort_keys=True)
        writer.writerow(row)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_catalog = export_products
products_csv = export_products_csv
