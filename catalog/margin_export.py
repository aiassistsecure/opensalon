"""Per-product margin CSV / dict export for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a sale, product, or stock
movement.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module renders the existing per-product margin
report (:func:`catalog.margin.product_margin`) as a plain,
JSON-serializable list of dicts (:func:`export_product_margin`)
and as a CSV string (:func:`export_product_margin_csv`) built from
that same list, so the two formats can never disagree — one source
of truth. Nothing is recomputed here: units and snapshot revenue
come verbatim from the margin report's rows (which reuse
:mod:`catalog.product_sales`), and cost / margin / margin percent
come verbatim from the same rows, current-cost caveat included —
``SaleItem`` has no cost snapshot, so cost is the product's
current ``cost_price`` (see :mod:`catalog.margin`). Row ordering
is the report's: ``retail_revenue`` descending, ``units_sold``
descending, then product name and id.

Columns are only fields the report rows actually carry:

- ``product_id`` / ``product_name``: from ``row.product``.
- ``sku`` / ``barcode``: copied from the product by the report.
- ``units_sold`` / ``retail_revenue``: the sales figures.
- ``unit_cost``: the product's current ``cost_price``.
- ``cost`` / ``margin`` / ``margin_percent``: the derived figures.

Money and percents are rendered as strings from ``Decimal`` to
two places, never passed through a float. A ``None`` value (no
cost recorded, or ``margin_percent`` on zero revenue) renders as
an empty string in both formats.

Optional window: both exports accept the same optional
``start`` / ``end`` (aliases ``start_date`` / ``end_date``) as
:func:`catalog.margin.product_margin` and pass them verbatim.
With no window the output is byte-identical to the historic
export (keys/header exactly :data:`MARGIN_FIELDNAMES`). With a
window, ``sales_start_date`` / ``sales_end_date`` keys are
appended to every record so the window is documented, never
silent.
"""
import csv
import io
from decimal import Decimal

from catalog.margin import product_margin

__all__ = [
    "MARGIN_FIELDNAMES",
    "PRODUCT_MARGIN_FIELDNAMES",
    "MARGIN_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_product_margin",
    "export_product_margin_csv",
    "product_margin_csv",
    "margin_csv",
]

#: Column / key order shared by the dict export and the CSV export.
MARGIN_FIELDNAMES = [
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "units_sold",
    "retail_revenue",
    "unit_cost",
    "cost",
    "margin",
    "margin_percent",
]

PRODUCT_MARGIN_FIELDNAMES = MARGIN_FIELDNAMES
MARGIN_EXPORT_FIELDNAMES = MARGIN_FIELDNAMES
EXPORT_FIELDNAMES = MARGIN_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


#: Extra keys appended only on a windowed export (see docstring).
WINDOW_FIELDNAMES = ["sales_start_date", "sales_end_date"]


def _record(row):
    record = {
        "product_id": row.product.pk,
        "product_name": row.product.name,
        "sku": row.sku,
        "barcode": row.barcode,
        "units_sold": int(row.units_sold),
        "retail_revenue": _money(row.retail_revenue),
        "unit_cost": _money(row.unit_cost),
        "cost": _money(row.cost),
        "margin": _money(row.margin),
        "margin_percent": _money(row.margin_percent),
    }
    if row.start_date is not None or row.end_date is not None:
        record.update({
            "sales_start_date": (
                row.start_date.isoformat() if row.start_date else ""),
            "sales_end_date": (
                row.end_date.isoformat() if row.end_date else ""),
        })
    return record


def export_product_margin(salon, start=None, end=None, *,
                          start_date=None, end_date=None):
    """Return ``salon``'s margin rows as a list of dicts.

    Each entry is a dict with exactly :data:`MARGIN_FIELDNAMES`
    keys (plus the window documentation keys on a windowed
    export), built directly from
    :func:`catalog.margin.product_margin`. Only ``salon``'s
    products are included, in the report's order. A salon with no
    products returns ``[]``. Records nothing.
    """
    return [_record(row) for row in product_margin(
        salon, start=start, end=end,
        start_date=start_date, end_date=end_date)]


def export_product_margin_csv(salon, start=None, end=None, *,
                              start_date=None, end_date=None):
    """Return ``salon``'s margin report as a CSV string.

    The header row is :data:`MARGIN_FIELDNAMES` (plus the window
    documentation columns on a windowed export) and every data
    row comes from :func:`export_product_margin` with the same
    salon and window, so the CSV and list exports always agree.
    A salon with no products exports as the header row alone.
    Lines end with ``"\\n"``. Records nothing.
    """
    records = export_product_margin(
        salon, start=start, end=end,
        start_date=start_date, end_date=end_date)
    fieldnames = MARGIN_FIELDNAMES
    if records and "sales_start_date" in records[0]:
        fieldnames = MARGIN_FIELDNAMES + WINDOW_FIELDNAMES
    elif start is not None or end is not None or start_date is not None \
            or end_date is not None:
        fieldnames = MARGIN_FIELDNAMES + WINDOW_FIELDNAMES
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
product_margin_csv = export_product_margin_csv
margin_csv = export_product_margin_csv
