"""CSV export of the prior-week roster week comparison.

Backend only, read-only, built ON TOP of :mod:`team.prior_roster_week`
— figures verbatim. Rows: the salon total first
(``section="total"``), then one row per staff member
(``section="staff"``), then one row per staff member per
weekday (``section="staff_weekday"``; that member's
``total_minutes`` delta for the weekday plus the
``current_is_working`` / ``prior_is_working`` pair), then one
row per weekday (``section="weekday"``; ``date`` is the
current week's day, ``prior_date`` its prior-week
counterpart, ``weekday`` Monday=0). Weekday rows carry
``total_minutes`` + ``working_staff``; their ``working_days``
columns are empty, as are staff/total rows' ``working_staff``
columns. The ``is_working`` columns are populated only on
``staff_weekday`` rows. Percent changes render to two
places; ``None`` empty.
"""
import csv
import io

from team.prior_roster_week import prior_roster_week_report

__all__ = ["PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES", "PRIOR_ROSTER_WEEK_FIELDNAMES",
           "EXPORT_FIELDNAMES", "export_prior_roster_week",
           "export_prior_roster_week_csv", "prior_roster_week_csv",
           "export_prior_period_roster_week_csv"]
_METRICS = ["total_minutes", "working_days"]
_WEEKDAY_METRICS = ["total_minutes", "working_staff"]
_ALL_METRICS = _METRICS + ["working_staff"]
PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES = (
    ["salon_id", "current_week_start", "current_week_end", "prior_week_start",
     "prior_week_end", "section", "staff_member_id", "staff_name",
     "weekday", "weekday_name", "date", "prior_date"]
    + [n for m in _ALL_METRICS for n in
       (f"current_{m}", f"prior_{m}", f"{m}_delta", f"{m}_percent_change")]
    + ["current_is_working", "prior_is_working"])
PRIOR_ROSTER_WEEK_FIELDNAMES = PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def _rows(result):
    base = {"salon_id": result.salon_id,
            "current_week_start": result.week_start.isoformat() if result.week_start else "",
            "current_week_end": result.week_end.isoformat() if result.week_end else "",
            "prior_week_start": result.prior_week_start.isoformat() if result.prior_week_start else "",
            "prior_week_end": result.prior_week_end.isoformat() if result.prior_week_end else ""}

    def build(section, staff_id, staff_name, weekday, source, metrics):
        row = {**base, "section": section, "staff_member_id": staff_id,
               "staff_name": staff_name,
               "weekday": weekday.weekday if weekday else "",
               "weekday_name": weekday.weekday_name if weekday else "",
               "date": weekday.day.isoformat() if weekday and weekday.day else "",
               "prior_date": weekday.prior_day.isoformat() if weekday and weekday.prior_day else ""}
        for m in _ALL_METRICS:
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
        if section == "staff_weekday":
            row["current_is_working"] = bool(source.current_is_working)
            row["prior_is_working"] = bool(source.prior_is_working)
        else:
            row["current_is_working"] = ""
            row["prior_is_working"] = ""
        return row

    rows = [build("total", "", "", None, result, _METRICS)]
    rows += [build("staff", s.staff_member_id, s.staff_name, None, s,
                   _METRICS) for s in result.by_staff]
    rows += [build("staff_weekday", s.staff_member_id, s.staff_name, w, w,
                   ["total_minutes"])
             for s in result.by_staff for w in s.by_weekday]
    rows += [build("weekday", "", "", w, w, _WEEKDAY_METRICS)
             for w in result.by_weekday]
    return rows


def export_prior_roster_week(*args, **kwargs):
    """Return the comparison as a list of dicts. Read-only."""
    return _rows(prior_roster_week_report(*args, **kwargs))


def export_prior_roster_week_csv(*args, **kwargs):
    """Return the comparison as a CSV string. Read-only."""
    result = prior_roster_week_report(*args, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in _rows(result):
        writer.writerow(record)
    return buffer.getvalue()


prior_roster_week_csv = export_prior_roster_week_csv
export_prior_period_roster_week_csv = export_prior_roster_week_csv
