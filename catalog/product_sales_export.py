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

Optional window: the export accepts the same optional
``start`` / ``end`` (aliases ``start_date`` / ``end_date``) as
:func:`catalog.product_sales.product_sales` and passes them
verbatim. With no window the CSV is byte-identical to the
historic export (header :data:`PRODUCT_SALES_FIELDNAMES` only).
With a window, three documentation columns are appended —
``sales_start_date``, ``sales_end_date``, ``stock_scope`` — so
the windowed units/revenue are never silently mixed with the
all-time stock figures (``stock_scope`` is ``"all_time"``);
the historic columns keep their order and meaning.
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


#: Extra columns appended only on a windowed export (see docstring).
WINDOW_FIELDNAMES = ["sales_start_date", "sales_end_date", "stock_scope"]


def export_product_sales_csv(salon, start=None, end=None, *,
                             start_date=None, end_date=None):
    """Return ``salon``'s per-product sales report as a CSV string.

    The header row is :data:`PRODUCT_SALES_FIELDNAMES` and every
    data row comes verbatim from
    :func:`catalog.product_sales.product_sales` for the same
    salon, in that service's order. A salon with no products
    exports as the header row alone. Lines end with ``"\\n"``.
    Records nothing. On a windowed export the documentation
    columns in :data:`WINDOW_FIELDNAMES` are appended.
    """
    report = product_sales(salon, start=start, end=end,
                           start_date=start_date, end_date=end_date)
    windowed = report.start_date is not None or report.end_date is not None
    fieldnames = (PRODUCT_SALES_FIELDNAMES + WINDOW_FIELDNAMES
                  if windowed else PRODUCT_SALES_FIELDNAMES)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in report.rows:
        record = {
            "product_id": row.product.pk,
            "product_name": row.product.name,
            "sku": row.sku,
            "barcode": row.barcode,
            "units_sold": int(row.units_sold),
            "retail_revenue": _money(row.retail_revenue),
            "current_stock": int(row.current_stock),
            "average_stock": _ratio(row.average_stock),
            "stock_turns": _ratio(row.stock_turns),
        }
        if windowed:
            record.update({
                "sales_start_date": (
                    row.start_date.isoformat() if row.start_date else ""),
                "sales_end_date": (
                    row.end_date.isoformat() if row.end_date else ""),
                "stock_scope": row.stock_scope,
            })
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
product_sales_csv = export_product_sales_csv
