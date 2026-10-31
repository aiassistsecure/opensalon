"""Low-stock CSV export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a product or a stock movement.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module renders the existing low-stock report
(:func:`catalog.low_stock.low_stock`) as a plain, JSON-serializable
list of dicts (:func:`export_low_stock`) and as a CSV string
(:func:`export_low_stock_csv`) built from that same list, so the
two formats can never disagree — one source of truth.

Stock is derived, never stored, and is NOT recomputed here: every
row's ``current_stock`` comes verbatim from the ``LowStockRow``
returned by :func:`catalog.low_stock.low_stock` (whose ``on_hand``
is the movement-ledger ``SUM``). This module adds no second stock
calculation.

Fields per row — only fields the low-stock report actually
returns: ``product_id`` and ``product_name`` (from ``row.product``),
``sku``, ``barcode``, ``current_stock`` (the report's ``on_hand``),
and ``threshold`` (the threshold the product qualified under; the
report also exposes it as ``reorder_threshold``).

Threshold semantics are the report's own: ``threshold=None`` uses
``catalog.low_stock.DEFAULT_LOW_STOCK_THRESHOLD``, an invalid
threshold raises the report's ``ValueError``, and a product
qualifies when its on-hand quantity is at or below the threshold.
Row ordering is the report's: on-hand ascending, then product
name and id.
"""
import csv
import io

from catalog.low_stock import low_stock

__all__ = [
    "LOW_STOCK_FIELDNAMES",
    "export_low_stock",
    "export_low_stock_csv",
    "low_stock_csv",
]

#: Column / key order shared by the dict export and the CSV export.
LOW_STOCK_FIELDNAMES = [
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "current_stock",
    "threshold",
]


def _record(row):
    return {
        "product_id": row.product.pk,
        "product_name": row.product.name,
        "sku": row.sku,
        "barcode": row.barcode,
        "current_stock": int(row.on_hand),
        "threshold": int(row.threshold),
    }


def export_low_stock(salon, threshold=None):
    """Return ``salon``'s low-stock rows as a list of dicts.

    Each entry is a dict with exactly :data:`LOW_STOCK_FIELDNAMES`
    keys, built directly from :func:`catalog.low_stock.low_stock`
    with the same ``threshold`` argument. Only ``salon``'s products
    are included, in the report's order. When nothing is at or
    below the threshold, returns ``[]``. Records nothing.
    """
    return [_record(row) for row in low_stock(salon, threshold=threshold)]


def export_low_stock_csv(salon, threshold=None):
    """Return ``salon``'s low-stock report as a CSV string.

    The header row is :data:`LOW_STOCK_FIELDNAMES` and every data
    row comes from :func:`export_low_stock` with the same
    arguments, so the CSV and list exports always agree. When
    nothing is low on stock, exports as the header row alone.
    Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=LOW_STOCK_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_low_stock(salon, threshold=threshold):
        writer.writerow(record)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
low_stock_csv = export_low_stock_csv
