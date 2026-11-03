"""Prior-period product sales / margin CSV export services.

Backend only — no views, templates, or UI. Read-only.
Founding rule (Exit Principle): anything a salon can enter, it
can fully export. Renders
:func:`catalog.prior_product_sales.prior_product_sales` and
:func:`catalog.prior_product_sales.prior_product_margin` as
lists of dicts and as CSV strings built from those same lists,
so the two formats can never disagree — one source of truth;
figures verbatim, same arguments (``salon``, current window
``start`` / ``end``, aliases ``start_date`` / ``end_date``).
First row is the salon total (product fields empty; the margin
total's ``unit_cost`` / ``margin_percent`` columns are ``None``
— the margin report carries neither for a salon), then one row
per product in ``by_product`` order. Metrics flatten into
``current_*`` / ``prior_*`` / ``*_delta`` /
``*_percent_change`` columns; dict values are the raw ints /
Decimals (``None`` where the comparison carries it) and in CSV
they render to two places, ``None`` empty. The margin export's
``unit_cost`` is the product's current ``cost_price``, one
column, as the margin report carries it.
"""
import csv
import io

from catalog.prior_product_sales import (
    prior_product_margin, prior_product_sales)

__all__ = ["PRIOR_PRODUCT_SALES_FIELDNAMES",
           "PRIOR_PRODUCT_SALES_EXPORT_FIELDNAMES",
           "PRIOR_PRODUCT_MARGIN_FIELDNAMES",
           "PRIOR_PRODUCT_MARGIN_EXPORT_FIELDNAMES",
           "EXPORT_FIELDNAMES",
           "export_prior_product_sales", "export_prior_product_sales_csv",
           "prior_product_sales_csv", "export_prior_product_margin",
           "export_prior_product_margin_csv", "prior_product_margin_csv"]
_BASE = ["salon_id", "current_start_date", "current_end_date",
         "prior_start_date", "prior_end_date", "product_id",
         "product_name", "sku", "barcode"]
_SALES_METRICS = ["units_sold", "retail_revenue"]
_MARGIN_METRICS = ["units_sold", "retail_revenue", "cost", "margin",
                   "margin_percent"]


def _flat(metrics):
    return [n for m in metrics for n in
            (f"current_{m}", f"prior_{m}", f"{m}_delta",
             f"{m}_percent_change")]


PRIOR_PRODUCT_SALES_FIELDNAMES = _BASE + _flat(_SALES_METRICS)
PRIOR_PRODUCT_SALES_EXPORT_FIELDNAMES = PRIOR_PRODUCT_SALES_FIELDNAMES
PRIOR_PRODUCT_MARGIN_FIELDNAMES = _BASE + ["unit_cost"] + _flat(_MARGIN_METRICS)
PRIOR_PRODUCT_MARGIN_EXPORT_FIELDNAMES = PRIOR_PRODUCT_MARGIN_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_PRODUCT_SALES_FIELDNAMES


def _fill(row, metrics, source):
    """Flatten each metric's MetricDelta (or None) into ``row``."""
    for metric in metrics:
        comparison = source.get(metric)
        row[f"current_{metric}"] = comparison.current if comparison else None
        row[f"prior_{metric}"] = comparison.prior if comparison else None
        row[f"{metric}_delta"] = comparison.delta if comparison else None
        row[f"{metric}_percent_change"] = (
            comparison.percent_change if comparison else None)
    return row


def _rows(result, metrics, margin=False):
    iso = lambda d: d.isoformat() if d else ""  # noqa: E731
    base = {"salon_id": result.salon_id,
            "current_start_date": iso(result.start_date),
            "current_end_date": iso(result.end_date),
            "prior_start_date": iso(result.prior_start_date),
            "prior_end_date": iso(result.prior_end_date)}
    totals = {"units_sold": result.total_units_sold,
              "retail_revenue": result.total_retail_revenue}
    if margin:
        totals.update({"cost": result.total_cost,
                       "margin": result.total_margin})
    total_row = {**base, "product_id": "", "product_name": "",
                 "sku": "", "barcode": ""}
    if margin:
        total_row["unit_cost"] = None
    rows = [_fill(total_row, metrics, totals)]
    for r in result.by_product:
        row = {**base, "product_id": r.product_id,
               "product_name": r.product_name, "sku": r.sku,
               "barcode": r.barcode}
        if margin:
            row["unit_cost"] = r.unit_cost
        rows.append(_fill(row, metrics,
                          {m: getattr(r, m) for m in metrics}))
    return rows


def export_prior_product_sales(salon, start=None, end=None, *,
                               start_date=None, end_date=None):
    """Return the sales comparison as a list of dicts. Read-only.

    First entry is the salon total, then one per product; each
    has exactly :data:`PRIOR_PRODUCT_SALES_FIELDNAMES` keys.
    """
    return _rows(prior_product_sales(
        salon, start=start, end=end, start_date=start_date,
        end_date=end_date), _SALES_METRICS)


def export_prior_product_margin(salon, start=None, end=None, *,
                                start_date=None, end_date=None):
    """Return the margin comparison as a list of dicts. Read-only.

    First entry is the salon total, then one per product; each
    has exactly :data:`PRIOR_PRODUCT_MARGIN_FIELDNAMES` keys.
    """
    return _rows(prior_product_margin(
        salon, start=start, end=end, start_date=start_date,
        end_date=end_date), _MARGIN_METRICS, margin=True)


def _csv(records, fieldnames, metrics):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames,
                            lineterminator="\n")
    writer.writeheader()
    int_columns = {"current_units_sold", "prior_units_sold",
                   "units_sold_delta"}
    for record in records:
        row = dict(record)
        for metric in metrics:
            for column in (f"current_{metric}", f"prior_{metric}",
                           f"{metric}_delta",
                           f"{metric}_percent_change"):
                value = record[column]
                if value is None:
                    row[column] = ""
                elif column not in int_columns:
                    row[column] = f"{value:.2f}"
        if "unit_cost" in row:
            row["unit_cost"] = ("" if record["unit_cost"] is None
                                else f"{record['unit_cost']:.2f}")
        writer.writerow(row)
    return buffer.getvalue()


def export_prior_product_sales_csv(salon, start=None, end=None, *,
                                   start_date=None, end_date=None):
    """Return the prior-period product sales comparison as CSV.

    Header is :data:`PRIOR_PRODUCT_SALES_FIELDNAMES`; every data
    row comes from :func:`export_prior_product_sales` with the
    same arguments, so CSV and list exports agree. Lines end
    with ``"\\n"``.
    """
    return _csv(export_prior_product_sales(
        salon, start=start, end=end, start_date=start_date,
        end_date=end_date), PRIOR_PRODUCT_SALES_FIELDNAMES, _SALES_METRICS)


def export_prior_product_margin_csv(salon, start=None, end=None, *,
                                    start_date=None, end_date=None):
    """Return the prior-period product margin comparison as CSV.

    Header is :data:`PRIOR_PRODUCT_MARGIN_FIELDNAMES`; every data
    row comes from :func:`export_prior_product_margin` with the
    same arguments. Lines end with ``"\\n"``.
    """
    return _csv(export_prior_product_margin(
        salon, start=start, end=end, start_date=start_date,
        end_date=end_date), PRIOR_PRODUCT_MARGIN_FIELDNAMES,
        _MARGIN_METRICS)


#: Aliases, mirroring the naming convenience in sibling services.
prior_product_sales_csv = export_prior_product_sales_csv
prior_product_margin_csv = export_prior_product_margin_csv
