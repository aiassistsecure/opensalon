"""CSV export of the prior-week roster week comparison.

Backend only, read-only, built ON TOP of :mod:`team.prior_roster_week`
— figures verbatim. First row is the salon total, then one row per
staff member. Percent changes render to two places; ``None`` empty.
"""
import csv
import io

from team.prior_roster_week import prior_roster_week_report

__all__ = ["PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES", "PRIOR_ROSTER_WEEK_FIELDNAMES",
           "EXPORT_FIELDNAMES", "export_prior_roster_week",
           "export_prior_roster_week_csv", "prior_roster_week_csv",
           "export_prior_period_roster_week_csv"]
_METRICS = ["total_minutes", "working_days"]
PRIOR_ROSTER_WEEK_EXPORT_FIELDNAMES = (
    ["salon_id", "current_week_start", "current_week_end", "prior_week_start",
     "prior_week_end", "staff_member_id", "staff_name"]
    + [n for m in _METRICS for n in
       (f"current_{m}", f"prior_{m}", f"{m}_delta", f"{m}_percent_change")])
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

    def build(staff_id, staff_name, source):
        row = {**base, "staff_member_id": staff_id, "staff_name": staff_name}
        for m in _METRICS:
            d = getattr(source, m)
            row[f"current_{m}"] = d.current
            row[f"prior_{m}"] = d.prior
            row[f"{m}_delta"] = d.delta
            row[f"{m}_percent_change"] = _pct(d.percent_change)
        return row

    return [build("", "", result)] + [
        build(s.staff_member_id, s.staff_name, s) for s in result.by_staff]


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
