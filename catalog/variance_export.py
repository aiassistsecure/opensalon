"""Stocktake variance CSV export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a product or a stock movement.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module renders the existing stocktake variance
report (:func:`catalog.variance.stocktake_variance`) as a plain,
JSON-serializable list of dicts (:func:`export_stocktake_variance`)
and as a CSV string (:func:`export_stocktake_variance_csv`) built
from that same list, so the two formats can never disagree — one
source of truth.

Variance is NOT recomputed here: no re-counting, no re-valuing,
no re-querying. Every row comes verbatim from the
``VarianceLine`` objects returned by
:func:`catalog.variance.stocktake_variance` with the exact same
arguments (``sheet_or_salon`` and ``counts`` — see that service
for its input shapes and validation). Row ordering is the
service's (sheet order).

The one export-level case the service cannot represent: an
explicitly empty ``counts`` mapping (or an empty sheet/pairs
input) raises ``ValueError`` in the service, because a variance
needs both sides. For an export, nothing counted means nothing
to report, so that case exports as ``[]`` / the header row alone
instead of raising. Every other invalid input (negative counts,
unknown keys, duplicates) still raises the service's
``ValueError`` verbatim.

Columns are only fields the variance lines actually carry:

- ``product_id`` / ``product_name``: from ``line.product`` /
  ``line.name``.
- ``sku`` / ``barcode``: copied from the product by the service.
- ``expected_stock`` / ``counted_stock`` / ``difference``:
  the line's expected (sheet on-hand), counted, and
  ``counted - expected`` quantities.
- ``unit_price``: the line's retail (selling) unit price.
- ``retail_value_impact``: the line's
  ``difference * unit_price`` retail value impact.

Money is rendered as a string to two decimal places, never
passed through a float.
"""
import csv
import io
from decimal import Decimal

from catalog.variance import stocktake_variance

__all__ = [
    "VARIANCE_FIELDNAMES",
    "STOCKTAKE_VARIANCE_FIELDNAMES",
    "VARIANCE_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_stocktake_variance",
    "export_stocktake_variance_csv",
    "variance_csv",
    "stocktake_variance_csv",
]

#: Column / key order shared by the dict export and the CSV export.
VARIANCE_FIELDNAMES = [
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "expected_stock",
    "counted_stock",
    "difference",
    "unit_price",
    "retail_value_impact",
]

STOCKTAKE_VARIANCE_FIELDNAMES = VARIANCE_FIELDNAMES
VARIANCE_EXPORT_FIELDNAMES = VARIANCE_FIELDNAMES
EXPORT_FIELDNAMES = VARIANCE_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _is_empty_input(sheet_or_salon, counts):
    """True for an explicitly empty count/sheet (see docstring)."""
    try:
        if counts is not None:
            return len(counts) == 0
        return len(sheet_or_salon) == 0
    except TypeError:
        return False


def _record(line):
    return {
        "product_id": line.product.pk,
        "product_name": line.name,
        "sku": line.sku,
        "barcode": line.barcode,
        "expected_stock": int(line.expected_stock),
        "counted_stock": int(line.counted_stock),
        "difference": int(line.difference),
        "unit_price": _money(line.unit_price),
        "retail_value_impact": _money(line.retail_value_impact),
    }


def export_stocktake_variance(sheet_or_salon, counts=None):
    """Return stocktake variance lines as a list of dicts.

    Each entry is a dict with exactly :data:`VARIANCE_FIELDNAMES`
    keys, built directly from
    :func:`catalog.variance.stocktake_variance` called with the
    same arguments, in that service's order. Salon scoping is the
    service's: a salon argument builds that salon's sheet, and a
    sheet argument carries its own salon's rows. An explicitly
    empty input exports as ``[]`` (see module docstring).
    Records nothing.
    """
    if _is_empty_input(sheet_or_salon, counts):
        return []
    if counts is None:
        report = stocktake_variance(sheet_or_salon)
    else:
        report = stocktake_variance(sheet_or_salon, counts)
    return [_record(line) for line in report.lines]


def export_stocktake_variance_csv(sheet_or_salon, counts=None):
    """Return stocktake variance lines as a CSV string.

    The header row is :data:`VARIANCE_FIELDNAMES` and every data
    row comes from :func:`export_stocktake_variance` with the
    same arguments, so the CSV and list exports always agree.
    An explicitly empty input exports as the header row alone.
    Lines end with ``"\\n"``. Records nothing.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=VARIANCE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_stocktake_variance(sheet_or_salon, counts):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
variance_csv = export_stocktake_variance_csv
stocktake_variance_csv = export_stocktake_variance_csv
