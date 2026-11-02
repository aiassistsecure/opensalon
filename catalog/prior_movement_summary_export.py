"""Prior-period stock movement summary CSV export service.

Backend only — no views, templates, or UI. Read-only.
Founding rule (Exit Principle): anything a salon can enter, it
can fully export. Renders
:func:`catalog.prior_movement_summary.prior_movement_summary`
as a list of dicts (:func:`export_prior_movement_summary`) and
as a CSV string built from that same list, so the two formats
can never disagree — one source of truth; figures verbatim,
same arguments (``start``, ``end``, optional ``salon``). First
row is the salon total (product fields empty), then one row
per product in ``by_product`` order. Metrics flatten into
``current_*`` / ``prior_*`` / ``*_delta`` /
``*_percent_change`` columns; dict-export percent changes are
Decimals (``None`` when prior is zero) and ``by_kind`` columns
are per-kind dicts; in CSV they render to two places (``None``
empty) and ``by_kind`` as sorted-key JSON, per-kind percent
changes as strings or ``null``.
"""
import csv
import io
import json

from catalog.prior_movement_summary import prior_movement_summary

__all__ = ["PRIOR_MOVEMENT_SUMMARY_FIELDNAMES",
           "PRIOR_MOVEMENT_SUMMARY_EXPORT_FIELDNAMES", "EXPORT_FIELDNAMES",
           "export_prior_movement_summary",
           "export_prior_movement_summary_csv", "prior_movement_summary_csv"]
_BASE = ["salon_id", "current_start_date", "current_end_date",
         "prior_start_date", "prior_end_date", "product_id", "product_name",
         "sku", "barcode"]
_METRICS = ["movement_count", "net_delta"]
PRIOR_MOVEMENT_SUMMARY_FIELDNAMES = (
    _BASE + [n for m in _METRICS for n in
             (f"current_{m}", f"prior_{m}", f"{m}_delta",
              f"{m}_percent_change")]
    + ["current_by_kind", "prior_by_kind", "by_kind_delta",
       "by_kind_percent_change"])
PRIOR_MOVEMENT_SUMMARY_EXPORT_FIELDNAMES = PRIOR_MOVEMENT_SUMMARY_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_MOVEMENT_SUMMARY_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def _record(base, product_id, product_name, sku, barcode, source):
    row = {**base, "product_id": product_id, "product_name": product_name,
           "sku": sku, "barcode": barcode}
    for metric in _METRICS:
        comparison = getattr(source, metric)
        row[f"current_{metric}"] = comparison.current
        row[f"prior_{metric}"] = comparison.prior
        row[f"{metric}_delta"] = comparison.delta
        row[f"{metric}_percent_change"] = comparison.percent_change
    kinds = source.by_kind
    row["current_by_kind"] = {k: d.current for k, d in kinds.items()}
    row["prior_by_kind"] = {k: d.prior for k, d in kinds.items()}
    row["by_kind_delta"] = {k: d.delta for k, d in kinds.items()}
    row["by_kind_percent_change"] = {
        k: d.percent_change for k, d in kinds.items()}
    return row


def _rows(result):
    iso = lambda d: d.isoformat() if d else ""  # noqa: E731
    base = {"salon_id": result.salon_id,
            "current_start_date": iso(result.start_date),
            "current_end_date": iso(result.end_date),
            "prior_start_date": iso(result.prior_start_date),
            "prior_end_date": iso(result.prior_end_date)}
    return [_record(base, "", "", "", "", result)] + [
        _record(base, r.product_id, r.product_name, r.sku, r.barcode, r)
        for r in result.by_product]


def export_prior_movement_summary(start, end, salon=None):
    """Return the comparison as a list of dicts. Read-only.

    First entry is the salon total, then one per product; each
    has exactly :data:`PRIOR_MOVEMENT_SUMMARY_FIELDNAMES` keys.
    A window pair with no movements returns the total row alone.
    """
    return _rows(prior_movement_summary(start, end, salon=salon))


def export_prior_movement_summary_csv(start, end, salon=None):
    """Return the prior-period movement summary as a CSV string.

    Header is :data:`PRIOR_MOVEMENT_SUMMARY_FIELDNAMES`; every
    data row comes from :func:`export_prior_movement_summary`
    with the same arguments, so CSV and list exports agree.
    Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PRIOR_MOVEMENT_SUMMARY_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in export_prior_movement_summary(start, end, salon=salon):
        row = dict(record)
        for metric in _METRICS:
            row[f"{metric}_percent_change"] = _pct(
                record[f"{metric}_percent_change"])
        for column in ("current_by_kind", "prior_by_kind", "by_kind_delta"):
            row[column] = json.dumps(record[column], sort_keys=True)
        row["by_kind_percent_change"] = json.dumps(
            {k: (None if v is None else f"{v:.2f}")
             for k, v in record["by_kind_percent_change"].items()},
            sort_keys=True)
        writer.writerow(row)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
prior_movement_summary_csv = export_prior_movement_summary_csv
