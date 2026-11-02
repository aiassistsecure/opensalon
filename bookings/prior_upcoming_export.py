"""CSV + dict export of the prior (elapsed-window) upcoming counts.

Backend only, read-only. Built ON TOP of
:mod:`bookings.prior_upcoming` — figures verbatim, never
recounted. The prior side is labelled ``elapsed`` throughout
(columns and values), so booked-ahead vs realized is never
blurred. CSV and dict are built from ONE row list
(:func:`_rows`), so they cannot disagree: salon total row,
then offset-paired per-day rows, then per-staff rows. Percent
changes render to two places; ``None`` renders empty in CSV.
Lines end ``"\\n"``.
"""
import csv
import io

from bookings.prior_upcoming import prior_upcoming_report

__all__ = ["PRIOR_UPCOMING_EXPORT_FIELDNAMES",
           "PRIOR_UPCOMING_FIELDNAMES", "EXPORT_FIELDNAMES",
           "export_prior_upcoming_csv", "prior_upcoming_csv",
           "export_prior_upcoming_dict", "prior_upcoming_dict"]

PRIOR_UPCOMING_EXPORT_FIELDNAMES = [
    "salon_id", "section", "current_start", "current_end",
    "elapsed_start", "elapsed_end", "days", "date", "elapsed_date",
    "staff_member_id", "staff_name", "current_count",
    "elapsed_count", "count_delta", "count_percent_change",
    "prior_label",
]
PRIOR_UPCOMING_FIELDNAMES = PRIOR_UPCOMING_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_UPCOMING_EXPORT_FIELDNAMES

def _pct(value):
    return "" if value is None else f"{value:.2f}"

def _iso(value):
    return value.isoformat() if value else ""

def _row(report, section, date, elapsed_date, staff_id, staff_name, delta):
    return {"salon_id": (report.salon.pk if report.salon is not None
                         else ""),
            "section": section,
            "current_start": _iso(report.start),
            "current_end": _iso(report.end),
            "elapsed_start": _iso(report.elapsed_start),
            "elapsed_end": _iso(report.elapsed_end),
            "days": report.days,
            "date": _iso(date), "elapsed_date": _iso(elapsed_date),
            "staff_member_id": staff_id, "staff_name": staff_name,
            "current_count": delta.current, "elapsed_count": delta.prior,
            "count_delta": delta.delta,
            "count_percent_change": delta.percent_change,
            "prior_label": "elapsed"}

def _rows(report):
    rows = [_row(report, "total", None, None, "", "", report.total)]
    rows += [_row(report, "day", d.date, d.elapsed_date, "", "", d.count)
             for d in report.by_day]
    rows += [_row(report, "staff", None, None, s.staff_member_id,
                  s.staff_name, s.count) for s in report.by_staff]
    return rows

def export_prior_upcoming_dict(salon, start=None, days=7, **kwargs):
    """Return the comparison as plain dicts, from the shared row list."""
    r = prior_upcoming_report(salon, start, days, **kwargs)
    return {"salon_id": r.salon.pk if r.salon is not None else None,
            **r.as_dict(), "rows": _rows(r)}

def export_prior_upcoming_csv(salon, start=None, days=7, **kwargs):
    """Return the comparison as CSV, from the same shared row list."""
    r = prior_upcoming_report(salon, start, days, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer,
                            fieldnames=PRIOR_UPCOMING_EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for row in _rows(r):
        writer.writerow({**row, "count_percent_change":
                         _pct(row["count_percent_change"])})
    return buffer.getvalue()

prior_upcoming_csv = export_prior_upcoming_csv
prior_upcoming_dict = export_prior_upcoming_dict
