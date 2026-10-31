"""Stock valuation CSV export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a product or a stock movement.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module renders the existing stock valuation
report (:func:`catalog.valuation.stock_valuation`) as a CSV
string built directly from that report's rows, so the export can
never disagree with the service — one source of truth.

Valuation is NOT recomputed here: no re-valuing, no re-querying.
Every row comes verbatim from the ``ValuationRow`` objects
returned by :func:`catalog.valuation.stock_valuation` (whose
on-hand quantities are the movement-ledger ``SUM`` and whose
values are on the **retail** basis — ``Product.price`` is the
selling price; there is no cost price, and nothing here reports
cost, margin, or profit). Row ordering is the service's:
``retail_value`` descending, then product name and id.

Columns are only fields the valuation rows actually carry:

- ``product_id`` / ``product_name``: from ``row.product``.
- ``sku`` / ``barcode``: copied from the product by the service.
- ``on_hand``: the row's movement-derived on-hand quantity.
- ``unit_price``: the row's retail (selling) unit price.
- ``retail_value``: the row's ``on_hand * unit_price`` value.

Money is rendered as a string to two decimal places, never
passed through a float.
"""
import csv
import io
from decimal import Decimal

from catalog.valuation import stock_valuation

__all__ = [
    "VALUATION_FIELDNAMES",
    "STOCK_VALUATION_FIELDNAMES",
    "VALUATION_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_stock_valuation_csv",
    "valuation_csv",
    "stock_valuation_csv",
]

#: Column order of the CSV export.
VALUATION_FIELDNAMES = [
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "on_hand",
    "unit_price",
    "retail_value",
]

STOCK_VALUATION_FIELDNAMES = VALUATION_FIELDNAMES
VALUATION_EXPORT_FIELDNAMES = VALUATION_FIELDNAMES
EXPORT_FIELDNAMES = VALUATION_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_stock_valuation_csv(salon):
    """Return ``salon``'s stock valuation as a CSV string.

    The header row is :data:`VALUATION_FIELDNAMES` and every data
    row comes verbatim from
    :func:`catalog.valuation.stock_valuation` for the same salon,
    in that service's order. Only ``salon``'s active products are
    included (the service's scoping). A salon with no active
    products exports as the header row alone. Lines end with
    ``"\\n"``. Records nothing.
    """
    report = stock_valuation(salon)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=VALUATION_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in report.rows:
        writer.writerow({
            "product_id": row.product.pk,
            "product_name": row.product.name,
            "sku": row.sku,
            "barcode": row.barcode,
            "on_hand": int(row.on_hand),
            "unit_price": _money(row.unit_price),
            "retail_value": _money(row.retail_value),
        })
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
valuation_csv = export_stock_valuation_csv
stock_valuation_csv = export_stock_valuation_csv
