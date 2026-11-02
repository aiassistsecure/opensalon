"""CSV + dict export of the prior-period status counts comparison.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`bookings.prior_status_counts` —
figures verbatim, never recounted. First data row is the salon
total (``status`` = ``"total"``), then one row per status in
``by_status`` order. Percent changes render to two places;
``None`` renders empty in CSV. Lines end ``"\\n"``.
"""
import csv
import io

from bookings.prior_status_counts import prior_status_counts_report

__all__ = [
    "PRIOR_STATUS_COUNTS_EXPORT_FIELDNAMES", "PRIOR_STATUS_COUNTS_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_prior_status_counts_csv",
    "prior_status_counts_csv", "export_prior_period_status_counts_csv",
    "export_prior_status_counts_dict", "prior_status_counts_dict",
    "export_prior_period_status_counts_dict",
]

PRIOR_STATUS_COUNTS_EXPORT_FIELDNAMES = [
    "salon_id", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "status",
    "current_count", "prior_count", "delta", "percent_change",
]
PRIOR_STATUS_COUNTS_FIELDNAMES = PRIOR_STATUS_COUNTS_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_STATUS_COUNTS_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def _rows(report):
    metrics = [("total", report.total)] + list(report.by_status.items())
    return [{
        "salon_id": report.salon.pk if report.salon is not None else "",
        "current_start_date": report.start_date.isoformat() if report.start_date else "",
        "current_end_date": report.end_date.isoformat() if report.end_date else "",
        "prior_start_date": report.prior_start_date.isoformat() if report.prior_start_date else "",
        "prior_end_date": report.prior_end_date.isoformat() if report.prior_end_date else "",
        "status": status, "current_count": m.current, "prior_count": m.prior,
        "delta": m.delta, "percent_change": m.percent_change,
    } for status, m in metrics]


def export_prior_status_counts_dict(salon, date_from=None, date_to=None, *,
                                    start_date=None, end_date=None, **kwargs):
    """Return the comparison as plain dicts (one row per status)."""
    r = prior_status_counts_report(
        salon, date_from, date_to, start_date=start_date,
        end_date=end_date, **kwargs)
    return {"salon_id": r.salon.pk if r.salon is not None else None,
            **r.as_dict(), "rows": _rows(r)}


def export_prior_status_counts_csv(salon, date_from=None, date_to=None, *,
                                   start_date=None, end_date=None, **kwargs):
    """Return the prior-period status counts comparison as CSV.

    Accepts exactly the parameters of
    :func:`bookings.prior_status_counts.prior_status_counts_report`,
    passed through unchanged (a reversed window raises
    ``ValueError`` from that service).
    """
    r = prior_status_counts_report(
        salon, date_from, date_to, start_date=start_date,
        end_date=end_date, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_STATUS_COUNTS_EXPORT_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()
    for row in _rows(r):
        writer.writerow({**row, "percent_change": _pct(row["percent_change"])})
    return buffer.getvalue()


prior_status_counts_csv = export_prior_status_counts_csv
export_prior_period_status_counts_csv = export_prior_status_counts_csv
prior_status_counts_dict = export_prior_status_counts_dict
export_prior_period_status_counts_dict = export_prior_status_counts_dict
