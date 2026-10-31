"""Stocktake sheet CSV export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a product or a stock movement.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module renders the existing stocktake sheet
service (:func:`catalog.stocktake_sheet.stocktake_sheet`) as a
plain, JSON-serializable list of dicts
(:func:`export_stocktake_sheet`) and as a CSV string
(:func:`export_stocktake_sheet_csv`) built from that same list,
so the two formats can never disagree — one source of truth.

The sheet is NOT recomputed here: no re-querying, no re-summing.
Every row comes verbatim from the ``StocktakeSheetRow`` objects
returned by :func:`catalog.stocktake_sheet.stocktake_sheet` for
the same salon (whose ``on_hand`` is the movement-ledger ``SUM``).
Row ordering is the service's: product name, then id. Salon
scoping is the service's: only that salon's **active** products
appear — this service is salon-scoped only, because
``stocktake_sheet`` itself takes a salon and has no unscoped form.

Columns are only fields the sheet rows actually carry:

- ``product_id`` / ``product_name``: from ``row.product`` /
  ``row.name``.
- ``sku`` / ``barcode``: copied from the product by the service.
- ``on_hand``: the row's movement-derived on-hand quantity.
- ``retail_price``: the row's retail (selling) price, copied
  from ``Product.price`` by the service.

Money is rendered as a string to two decimal places, never
passed through a float.
"""
import csv
import io
from decimal import Decimal

from catalog.stocktake_sheet import stocktake_sheet

__all__ = [
    "STOCKTAKE_SHEET_FIELDNAMES",
    "STOCKTAKE_SHEET_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_stocktake_sheet",
    "export_stocktake_sheet_csv",
    "stocktake_sheet_csv",
    "sheet_csv",
]

#: Column / key order shared by the dict export and the CSV export.
STOCKTAKE_SHEET_FIELDNAMES = [
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "on_hand",
    "retail_price",
]

STOCKTAKE_SHEET_EXPORT_FIELDNAMES = STOCKTAKE_SHEET_FIELDNAMES
EXPORT_FIELDNAMES = STOCKTAKE_SHEET_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _record(row):
    return {
        "product_id": row.product.pk,
        "product_name": row.name,
        "sku": row.sku,
        "barcode": row.barcode,
        "on_hand": int(row.on_hand),
        "retail_price": _money(row.retail_price),
    }


def export_stocktake_sheet(salon):
    """Return ``salon``'s stocktake sheet as a list of dicts.

    Each entry is a dict with exactly
    :data:`STOCKTAKE_SHEET_FIELDNAMES` keys, built directly from
    :func:`catalog.stocktake_sheet.stocktake_sheet` for the same
    salon, in that service's order. Only ``salon``'s active
    products are included (the service's scoping). A salon with
    no active products exports as ``[]``. Records nothing.
    """
    return [_record(row) for row in stocktake_sheet(salon)]


def export_stocktake_sheet_csv(salon):
    """Return ``salon``'s stocktake sheet as a CSV string.

    The header row is :data:`STOCKTAKE_SHEET_FIELDNAMES` and
    every data row comes from :func:`export_stocktake_sheet`
    with the same argument, so the CSV and list exports always
    agree. A salon with no active products exports as the header
    row alone. Lines end with ``"\\n"``. Records nothing.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=STOCKTAKE_SHEET_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_stocktake_sheet(salon):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
stocktake_sheet_csv = export_stocktake_sheet_csv
sheet_csv = export_stocktake_sheet_csv
