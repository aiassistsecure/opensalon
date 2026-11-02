"""CSV + dict export of the prior-period payroll feed comparison.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`bookings.prior_payroll_feed` —
figures verbatim, never recounted. The CSV is built from the
one dict list (:func:`prior_payroll_feed_rows`): first data row
is the salon total (staff fields empty), then one row per staff
member in ``by_staff`` order. Percent changes render to two
places; ``None`` renders empty in CSV. Lines end ``"\\n"``.
"""
import csv
import io

from bookings.prior_payroll_feed import METRICS, prior_payroll_feed_report

__all__ = ["PRIOR_PAYROLL_FEED_EXPORT_FIELDNAMES",
           "PRIOR_PAYROLL_FEED_FIELDNAMES", "EXPORT_FIELDNAMES",
           "prior_payroll_feed_rows", "export_prior_payroll_feed_rows",
           "export_prior_payroll_feed_dict", "prior_payroll_feed_dict",
           "export_prior_payroll_feed_csv", "prior_payroll_feed_csv",
           "export_prior_period_payroll_feed_csv"]

PRIOR_PAYROLL_FEED_EXPORT_FIELDNAMES = [
    "salon_id", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "staff_member_id", "staff_name",
]
for _m in METRICS:
    PRIOR_PAYROLL_FEED_EXPORT_FIELDNAMES += [
        f"current_{_m}", f"prior_{_m}", f"{_m}_delta",
        f"{_m}_percent_change"]
PRIOR_PAYROLL_FEED_FIELDNAMES = PRIOR_PAYROLL_FEED_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_PAYROLL_FEED_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def _flat(report, staff_id, staff_name, source):
    row = {"salon_id": report.salon.pk if report.salon is not None else "",
           "current_start_date": report.start_date.isoformat() if report.start_date else "",
           "current_end_date": report.end_date.isoformat() if report.end_date else "",
           "prior_start_date": report.prior_start_date.isoformat() if report.prior_start_date else "",
           "prior_end_date": report.prior_end_date.isoformat() if report.prior_end_date else "",
           "staff_member_id": staff_id, "staff_name": staff_name}
    for m in METRICS:
        d = getattr(source, m)
        row[f"current_{m}"] = d.current
        row[f"prior_{m}"] = d.prior
        row[f"{m}_delta"] = d.delta
        row[f"{m}_percent_change"] = d.percent_change
    return row


def prior_payroll_feed_rows(salon, date_from=None, date_to=None, **kwargs):
    """Return the comparison as a list of plain dicts.

    First entry is the salon total, then one dict per staff
    member in ``by_staff`` order. This one list is the source
    for the CSV export.
    """
    r = prior_payroll_feed_report(salon, date_from, date_to, **kwargs)
    return [_flat(r, "", "", r)] + [
        _flat(r, s.staff_member_id, s.staff_name, s) for s in r.by_staff]


export_prior_payroll_feed_rows = prior_payroll_feed_rows
export_prior_payroll_feed_dict = prior_payroll_feed_rows
prior_payroll_feed_dict = prior_payroll_feed_rows


def export_prior_payroll_feed_csv(salon, date_from=None, date_to=None, **kwargs):
    """Return the comparison as CSV, built from the dict list."""
    rows = prior_payroll_feed_rows(salon, date_from, date_to, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter( buffer, fieldnames=PRIOR_PAYROLL_FEED_EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({ **row, **{f"{m}_percent_change": _pct(row[f"{m}_percent_change"]) for m in METRICS}, })
    return buffer.getvalue()


prior_payroll_feed_csv = export_prior_payroll_feed_csv
export_prior_period_payroll_feed_csv = export_prior_payroll_feed_csv
