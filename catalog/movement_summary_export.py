"""Stock movement summary CSV export service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a stock movement; the movement
ledger stays append-only and is only read here.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module renders the existing movement summary
service (:func:`catalog.movement_summary.movement_summary`) as a
plain, JSON-serializable list of dicts
(:func:`export_movement_summary`) and as a CSV string
(:func:`export_movement_summary_csv`) built from that same list,
so the two formats can never disagree — one source of truth.

Nothing is recomputed here: every row comes verbatim from the
summary's ``by_product`` rows, built with the exact same arguments
(``start``, ``end``, and optional ``salon`` — see that service for
its range semantics: required inclusive local-date bounds covering
whole days, a reversed or missing bound raises ``ValueError``).
Row ordering is the service's: product name, then id. Only
products with at least one movement in the range appear.

Fields per row are exactly
:data:`catalog.movement_summary.PRODUCT_FIELDNAMES`:
``product_id``, ``product_name``, ``sku``, ``barcode``,
``movement_count``, ``net_delta``, and ``by_kind`` (a dict of
per-kind delta sums; only kinds present for that product in the
range appear). In the CSV rendering ``by_kind`` is written as a
JSON object string with sorted keys, so no per-kind total is
lost; in the dict export it stays a dict. Negative sums are
reported as they stand, never clamped.
"""
import csv
import io
import json

from catalog.movement_summary import PRODUCT_FIELDNAMES, movement_summary

__all__ = [
    "MOVEMENT_SUMMARY_FIELDNAMES",
    "MOVEMENT_SUMMARY_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_movement_summary",
    "export_movement_summary_csv",
    "movement_summary_csv",
]

#: Column / key order shared by the dict export and the CSV export.
MOVEMENT_SUMMARY_FIELDNAMES = list(PRODUCT_FIELDNAMES)

MOVEMENT_SUMMARY_EXPORT_FIELDNAMES = MOVEMENT_SUMMARY_FIELDNAMES
EXPORT_FIELDNAMES = MOVEMENT_SUMMARY_FIELDNAMES


def _record(row):
    return {
        "product_id": row["product_id"],
        "product_name": row["product_name"],
        "sku": row["sku"],
        "barcode": row["barcode"],
        "movement_count": int(row["movement_count"]),
        "net_delta": int(row["net_delta"]),
        "by_kind": dict(row["by_kind"]),
    }


def export_movement_summary(start, end, salon=None):
    """Return the summary's per-product rows as a list of dicts.

    Each entry is a dict with exactly
    :data:`MOVEMENT_SUMMARY_FIELDNAMES` keys, built directly from
    :func:`catalog.movement_summary.movement_summary` with the
    same arguments. When ``salon`` is given, only that salon's
    movements count; otherwise every salon counts. A range with
    no movements returns ``[]``. Records nothing.
    """
    summary = movement_summary(start, end, salon=salon)
    return [_record(row) for row in summary.by_product]


def export_movement_summary_csv(start, end, salon=None):
    """Return the movement summary for the range as a CSV string.

    The header row is :data:`MOVEMENT_SUMMARY_FIELDNAMES` and
    every data row comes from :func:`export_movement_summary`
    with the same arguments, so the CSV and list exports always
    agree; ``by_kind`` is rendered as a JSON object string with
    sorted keys. A range with no movements exports as the header
    row alone. Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=MOVEMENT_SUMMARY_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for record in export_movement_summary(start, end, salon=salon):
        writer.writerow({
            **record,
            "by_kind": json.dumps(record["by_kind"], sort_keys=True),
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
movement_summary_csv = export_movement_summary_csv
