"""Per-product sales + stock turns CSV export for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a sale, product, or stock
movement.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module renders the existing per-product sales
report (:func:`catalog.product_sales.product_sales`) as a CSV
string built directly from that report's rows, so the export can
never disagree with the service — one source of truth. Nothing is
recomputed here: units, snapshot retail revenue, derived current
and average stock, and stock turns all come verbatim from the
``ProductSalesRow`` objects (completed product sale lines only;
turns safe on zero average stock — see
:mod:`catalog.product_sales`). Row ordering is the service's:
``retail_revenue`` descending, ``units_sold`` descending, then
product name and id.

Columns are only fields the report rows actually carry:

- ``product_id`` / ``product_name``: from ``row.product``.
- ``sku`` / ``barcode``: copied from the product by the service.
- ``units_sold``: completed product-line units for the product.
- ``retail_revenue``: snapshot revenue, money to two places.
- ``current_stock``: movement-derived stock at report time.
- ``average_stock`` / ``stock_turns``: rendered to four places.

Money and ratios are rendered as strings from ``Decimal``,
never passed through a float.
"""
import csv
import io
from decimal import Decimal

from catalog.product_sales import product_sales

__all__ = [
    "PRODUCT_SALES_FIELDNAMES",
    "PRODUCT_SALES_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_product_sales_csv",
    "product_sales_csv",
]

#: Column order of the CSV export.
PRODUCT_SALES_FIELDNAMES = [
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "units_sold",
    "retail_revenue",
    "current_stock",
    "average_stock",
    "stock_turns",
]

PRODUCT_SALES_EXPORT_FIELDNAMES = PRODUCT_SALES_FIELDNAMES
EXPORT_FIELDNAMES = PRODUCT_SALES_FIELDNAMES

_CENTS = Decimal("0.01")
_RATIO = Decimal("0.0001")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _ratio(value):
    return str(Decimal(value).quantize(_RATIO))


def export_product_sales_csv(salon):
    """Return ``salon``'s per-product sales report as a CSV string.

    The header row is :data:`PRODUCT_SALES_FIELDNAMES` and every
    data row comes verbatim from
    :func:`catalog.product_sales.product_sales` for the same
    salon, in that service's order. A salon with no products
    exports as the header row alone. Lines end with ``"\\n"``.
    Records nothing.
    """
    report = product_sales(salon)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRODUCT_SALES_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in report.rows:
        writer.writerow({
            "product_id": row.product.pk,
            "product_name": row.product.name,
            "sku": row.sku,
            "barcode": row.barcode,
            "units_sold": int(row.units_sold),
            "retail_revenue": _money(row.retail_revenue),
            "current_stock": int(row.current_stock),
            "average_stock": _ratio(row.average_stock),
            "stock_turns": _ratio(row.stock_turns),
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
product_sales_csv = export_product_sales_csv
