"""CSV + dict export of the prior-period break totals comparison.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`bookings.prior_break_totals` —
figures verbatim, never recounted. First data row is the salon
total (staff fields empty), then one row per staff member in
``by_staff`` order. Percent changes render to two places;
``None`` renders empty in CSV. Lines end ``"\\n"``.
"""
import csv
import io

from bookings.prior_break_totals import METRICS, prior_break_totals_report

__all__ = ["PRIOR_BREAK_TOTALS_EXPORT_FIELDNAMES", "PRIOR_BREAK_TOTALS_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_prior_break_totals_csv", "prior_break_totals_csv",
    "export_prior_period_break_totals_csv", "export_prior_break_totals_dict",
    "prior_break_totals_dict", "export_prior_period_break_totals_dict"]

PRIOR_BREAK_TOTALS_EXPORT_FIELDNAMES = [
    "salon_id", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "staff_member_id", "staff_name",
]
for _m in METRICS:
    PRIOR_BREAK_TOTALS_EXPORT_FIELDNAMES += [
        f"current_{_m}", f"prior_{_m}", f"{_m}_delta",
        f"{_m}_percent_change"]
PRIOR_BREAK_TOTALS_FIELDNAMES = PRIOR_BREAK_TOTALS_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_BREAK_TOTALS_EXPORT_FIELDNAMES


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


def _rows(report):
    return [_flat(report, "", "", report)] + [
        _flat(report, s.staff_member_id, s.staff_name, s) for s in report.by_staff]


def export_prior_break_totals_dict(salon, date_from=None, date_to=None, **kwargs):
    """Return the comparison as plain dicts (total + per-staff rows)."""
    r = prior_break_totals_report(salon, date_from, date_to, **kwargs)
    return {"salon_id": r.salon.pk if r.salon is not None else None, **r.as_dict(), "rows": _rows(r)}


def export_prior_break_totals_csv(salon, date_from=None, date_to=None, **kwargs):
    """Return the comparison as CSV (params pass through unchanged)."""
    r = prior_break_totals_report(salon, date_from, date_to, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_BREAK_TOTALS_EXPORT_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()
    for row in _rows(r):
        writer.writerow({
            **row,
            **{f"{m}_percent_change": _pct(row[f"{m}_percent_change"])
               for m in METRICS},
        })
    return buffer.getvalue()


prior_break_totals_csv = export_prior_break_totals_csv
export_prior_period_break_totals_csv = export_prior_break_totals_csv
prior_break_totals_dict = export_prior_break_totals_dict
export_prior_period_break_totals_dict = export_prior_break_totals_dict
