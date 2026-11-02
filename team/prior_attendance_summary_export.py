"""CSV export of the prior-period attendance summary comparison.

Backend only, read-only, built ON TOP of
:mod:`team.prior_attendance_summary` — figures verbatim. Rows:
the salon total first (``section="total"``), then one row per
staff member (``section="staff"``), then one row per
offset-aligned per-day pair (``section="day"``; ``date`` is the
current day, ``prior_date`` its prior-window counterpart),
then one row per member per offset-aligned day pair
(``section="staff_day"``, the report's ``per_staff_per_day``
cross grain). Percent changes render to two places; ``None``
empty.
"""
import csv
import io

from team.prior_attendance_summary import prior_attendance_summary_report

__all__ = ["PRIOR_ATTENDANCE_SUMMARY_EXPORT_FIELDNAMES",
           "PRIOR_ATTENDANCE_SUMMARY_FIELDNAMES", "EXPORT_FIELDNAMES",
           "export_prior_attendance_summary", "export_prior_attendance_summary_csv",
           "prior_attendance_summary_csv", "export_prior_period_attendance_summary_csv"]
_METRICS = ["sessions_count", "closed_sessions", "open_sessions", "total_minutes"]
_DAY_METRICS = _METRICS + ["staff_count"]
PRIOR_ATTENDANCE_SUMMARY_EXPORT_FIELDNAMES = (
    ["salon_id", "current_start_date", "current_end_date", "prior_start_date",
     "prior_end_date", "section", "staff_member_id", "staff_name",
     "date", "prior_date"]
    + [n for m in _METRICS for n in
       (f"current_{m}", f"prior_{m}", f"{m}_delta", f"{m}_percent_change")]
    + [n for m in ["staff_count"] for n in
       (f"current_{m}", f"prior_{m}", f"{m}_delta", f"{m}_percent_change")])
PRIOR_ATTENDANCE_SUMMARY_FIELDNAMES = PRIOR_ATTENDANCE_SUMMARY_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_ATTENDANCE_SUMMARY_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def _rows(result):
    base = {"salon_id": result.salon_id,
            "current_start_date": result.start_date.isoformat() if result.start_date else "",
            "current_end_date": result.end_date.isoformat() if result.end_date else "",
            "prior_start_date": result.prior_start_date.isoformat() if result.prior_start_date else "",
            "prior_end_date": result.prior_end_date.isoformat() if result.prior_end_date else ""}

    def build(section, staff_id, staff_name, day, prior_day, source, metrics):
        row = {**base, "section": section, "staff_member_id": staff_id,
               "staff_name": staff_name,
               "date": day.isoformat() if day else "",
               "prior_date": prior_day.isoformat() if prior_day else ""}
        for m in _DAY_METRICS:
            if m in metrics:
                d = getattr(source, m)
                row[f"current_{m}"] = d.current
                row[f"prior_{m}"] = d.prior
                row[f"{m}_delta"] = d.delta
                row[f"{m}_percent_change"] = _pct(d.percent_change)
            else:
                row[f"current_{m}"] = ""
                row[f"prior_{m}"] = ""
                row[f"{m}_delta"] = ""
                row[f"{m}_percent_change"] = ""
        return row

    rows = [build("total", "", "", None, None, result, _METRICS)]
    rows += [build("staff", s.staff_member_id, s.staff_name, None, None, s,
                   _METRICS) for s in result.by_staff]
    rows += [build("day", "", "", d.day, d.prior_day, d, _DAY_METRICS)
             for d in result.per_day]
    rows += [build("staff_day", e.staff_member_id, e.staff_name, e.day,
                   e.prior_day, e, _METRICS)
             for e in result.per_staff_per_day]
    return rows


def export_prior_attendance_summary(*args, **kwargs):
    """Return the comparison as a list of dicts. Read-only."""
    return _rows(prior_attendance_summary_report(*args, **kwargs))


def export_prior_attendance_summary_csv(*args, **kwargs):
    """Return the comparison as a CSV string. Read-only."""
    result = prior_attendance_summary_report(*args, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PRIOR_ATTENDANCE_SUMMARY_EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in _rows(result):
        writer.writerow(record)
    return buffer.getvalue()


prior_attendance_summary_csv = export_prior_attendance_summary_csv
export_prior_period_attendance_summary_csv = export_prior_attendance_summary_csv
