"""CSV + dict export of the prior-period new-client comparison.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`clients.prior_new_clients` —
figures verbatim, never recounted. Count-shaped ONLY: no
client rows, ids, or names anywhere in this export. First data
row is the total (``day`` = ``"total"``), then one row per
current-window day in order, paired with its prior-window
counterpart day. Percent changes are Decimals in dict export
(``None`` when prior is zero) and render to two places in CSV
(``None`` empty). Lines end ``"\\n"``.
"""
import csv
import io

from clients.prior_new_clients import prior_new_clients_report

__all__ = ["PRIOR_NEW_CLIENTS_FIELDNAMES", "PRIOR_NEW_CLIENTS_EXPORT_FIELDNAMES",
           "EXPORT_FIELDNAMES", "export_prior_new_clients",
           "export_prior_new_clients_csv", "export_prior_new_client_csv",
           "prior_new_clients_csv", "export_prior_new_clients_dict",
           "prior_new_clients_dict"]

PRIOR_NEW_CLIENTS_FIELDNAMES = [
    "salon_id", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "day", "prior_day",
    "current_count", "prior_count", "delta", "percent_change",
]
PRIOR_NEW_CLIENTS_EXPORT_FIELDNAMES = PRIOR_NEW_CLIENTS_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_NEW_CLIENTS_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def _rows(report):
    iso = lambda d: d.isoformat() if d else ""  # noqa: E731
    base = {"salon_id": report.salon.pk if report.salon is not None else "",
            "current_start_date": iso(report.start_date),
            "current_end_date": iso(report.end_date),
            "prior_start_date": iso(report.prior_start_date),
            "prior_end_date": iso(report.prior_end_date)}
    total = report.total
    rows = [{**base, "day": "total", "prior_day": "",
             "current_count": total.current, "prior_count": total.prior,
             "delta": total.delta, "percent_change": total.percent_change}]
    for day, row in report.by_day.items():
        rows.append({**base, "day": iso(day), "prior_day": iso(row.prior_date),
                     "current_count": row.current, "prior_count": row.prior,
                     "delta": row.delta, "percent_change": row.percent_change})
    return rows


def export_prior_new_clients(salon=None, start_date=None, end_date=None, **kwargs):
    """Return the comparison as a list of dicts.

    Arguments are exactly those of
    :func:`clients.prior_new_clients.prior_new_clients_report`,
    passed through unchanged. First entry is the total, then
    one per current-window day; each has exactly
    :data:`PRIOR_NEW_CLIENTS_FIELDNAMES` keys.
    """
    return _rows(prior_new_clients_report(salon, start_date, end_date, **kwargs))


def export_prior_new_clients_dict(salon=None, start_date=None, end_date=None,
                                  **kwargs):
    """Return the comparison as a structured dict with ``rows``."""
    report = prior_new_clients_report(salon, start_date, end_date, **kwargs)
    return {"salon_id": report.salon.pk if report.salon is not None else None,
            **report.as_dict(), "rows": _rows(report)}


def export_prior_new_clients_csv(salon=None, start_date=None, end_date=None,
                                 **kwargs):
    """Return the comparison as a CSV string.

    Header is :data:`PRIOR_NEW_CLIENTS_FIELDNAMES`; every data
    row comes from :func:`export_prior_new_clients` with the
    same arguments, so CSV and dict exports agree. A reversed
    or missing window raises ``ValueError`` from the service.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PRIOR_NEW_CLIENTS_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in export_prior_new_clients(salon, start_date, end_date, **kwargs):
        writer.writerow({**record, "percent_change": _pct(record["percent_change"])})
    return buffer.getvalue()


export_prior_new_client_csv = export_prior_new_clients_csv
prior_new_clients_csv = export_prior_new_clients_csv
prior_new_clients_dict = export_prior_new_clients_dict
