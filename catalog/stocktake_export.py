"""Completed stocktake CSV export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a product or a stock movement;
exporting a (salon, counts) pair uses the dry-run
:func:`catalog.stocktake.compute_variances`, which records nothing.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module renders a completed / computed stocktake
from :mod:`catalog.stocktake` — the reconciling service, distinct
from the read-only sheet (:mod:`catalog.stocktake_sheet`, exported
by :mod:`catalog.stocktake_sheet_export`) and from the sheet-based
variance analysis (:mod:`catalog.variance`, exported by
:mod:`catalog.variance_export`) — as a plain, JSON-serializable
list of dicts (:func:`export_stocktake_counts`) and as a CSV string
(:func:`export_stocktake_counts_csv`) built from that same list,
so the two formats can never disagree — one source of truth.

Gap evidence: ``variance_export`` covers ``catalog.variance`` and
``stocktake_sheet_export`` covers ``catalog.stocktake_sheet``, but
no module exported ``catalog.stocktake``'s ``Variance`` /
``StocktakeResult`` (the completed count, its caller-supplied
``reference``, its ``already_applied`` idempotency flag, and the id
of the reconciling ``STOCKTAKE`` movement, when one was recorded).
That completed-count record is what this module exports.

Input shapes:

- a :class:`catalog.stocktake.StocktakeResult` (the result of
  :func:`catalog.stocktake.reconcile_stocktake`), or
- ``(salon, counts)`` with the same ``counts`` mapping
  :func:`catalog.stocktake.compute_variances` accepts.

Columns are only fields the stocktake variances actually carry:

- ``reference`` / ``already_applied``: from the result; empty /
  ``False`` for the dry-run (salon, counts) form.
- ``product_id`` / ``product_name`` / ``sku`` / ``barcode``:
  from ``variance.product``.
- ``expected_stock`` / ``counted_stock`` / ``variance``:
  the variance's expected (derived), counted, and
  ``counted - expected`` quantities.
- ``movement_id``: the reconciling movement's id, or ``None``
  (empty in CSV) for a dry run or a zero variance.

An explicitly empty ``counts`` mapping exports as ``[]`` / the
header row alone instead of raising the service's ``ValueError``
(a variance needs both sides; an export of nothing counted is
nothing to report). Every other invalid input still raises the
service's ``ValueError`` verbatim. Salon scoping is the service's:
counts are resolved within the salon and foreign products raise.
"""
import csv
import io

from catalog.stocktake import StocktakeResult, compute_variances

__all__ = [
    "STOCKTAKE_FIELDNAMES",
    "STOCKTAKE_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_stocktake_counts",
    "export_stocktake_counts_csv",
    "export_completed_stocktake",
    "export_completed_stocktake_csv",
    "stocktake_csv",
    "stocktake_counts_csv",
]

#: Column / key order shared by the dict export and the CSV export.
STOCKTAKE_FIELDNAMES = [
    "reference",
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "expected_stock",
    "counted_stock",
    "variance",
    "movement_id",
    "already_applied",
]

STOCKTAKE_EXPORT_FIELDNAMES = STOCKTAKE_FIELDNAMES
EXPORT_FIELDNAMES = STOCKTAKE_FIELDNAMES


def _record(variance, reference, already_applied):
    product = variance.product
    movement = variance.movement
    return {
        "reference": reference,
        "product_id": product.pk,
        "product_name": product.name,
        "sku": product.sku,
        "barcode": product.barcode,
        "expected_stock": int(variance.expected_stock),
        "counted_stock": int(variance.counted_stock),
        "variance": int(variance.variance),
        "movement_id": movement.pk if movement is not None else None,
        "already_applied": bool(already_applied),
    }


def export_stocktake_counts(salon_or_result, counts=None):
    """Return completed stocktake counts as a list of dicts.

    Each entry is a dict with exactly :data:`STOCKTAKE_FIELDNAMES`
    keys, built directly from the ``Variance`` objects of a
    :class:`StocktakeResult` or from
    :func:`catalog.stocktake.compute_variances` for
    ``(salon, counts)``, in that service's order (sorted by product
    id). An explicitly empty ``counts`` mapping exports as ``[]``
    (see module docstring). Records nothing.
    """
    if isinstance(salon_or_result, StocktakeResult):
        result = salon_or_result
        return [
            _record(v, result.reference, result.already_applied)
            for v in result.variances
        ]
    if counts is not None and hasattr(counts, "__len__") and len(counts) == 0:
        return []
    variances = compute_variances(salon_or_result, counts)
    return [_record(v, "", False) for v in variances]


def export_stocktake_counts_csv(salon_or_result, counts=None):
    """Return completed stocktake counts as a CSV string.

    The header row is :data:`STOCKTAKE_FIELDNAMES` and every data
    row comes from :func:`export_stocktake_counts` with the same
    arguments, so the CSV and list exports always agree. An
    explicitly empty input exports as the header row alone.
    ``None`` movement ids render as an empty field. Lines end
    with ``"\\n"``. Records nothing.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=STOCKTAKE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_stocktake_counts(salon_or_result, counts):
        row = {
            **record,
            "movement_id": "" if record["movement_id"] is None
            else record["movement_id"],
        }
        writer.writerow(row)
    return buffer.getvalue()


#: Descriptive aliases, mirroring sibling services.
export_completed_stocktake = export_stocktake_counts
export_completed_stocktake_csv = export_stocktake_counts_csv
stocktake_csv = export_stocktake_counts_csv
stocktake_counts_csv = export_stocktake_counts_csv
