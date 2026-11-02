"""CSV export of the prior-period variance comparison.

Backend only, read-only, built ON TOP of :mod:`team.prior_variance`
— figures verbatim. First row is the salon total, then one row per
staff member. Percent changes render to two places; ``None`` empty.
"""
import csv
import io

from team.prior_variance import prior_variance_report

__all__ = ["PRIOR_VARIANCE_EXPORT_FIELDNAMES", "PRIOR_VARIANCE_FIELDNAMES",
           "EXPORT_FIELDNAMES", "export_prior_variance",
           "export_prior_variance_csv", "prior_variance_csv",
           "export_prior_period_variance_csv", "export_prior_roster_variance",
           "export_prior_roster_variance_csv"]
_METRICS = ["rostered_minutes", "actual_minutes", "variance_minutes",
            "days_rostered", "days_attended", "absence_days"]
PRIOR_VARIANCE_EXPORT_FIELDNAMES = (
    ["salon_id", "current_start_date", "current_end_date", "prior_start_date",
     "prior_end_date", "staff_member_id", "staff_name"]
    + [n for m in _METRICS for n in
       (f"current_{m}", f"prior_{m}", f"{m}_delta", f"{m}_percent_change")])
PRIOR_VARIANCE_FIELDNAMES = PRIOR_VARIANCE_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_VARIANCE_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def _rows(result):
    base = {"salon_id": result.salon_id,
            "current_start_date": result.start_date.isoformat() if result.start_date else "",
            "current_end_date": result.end_date.isoformat() if result.end_date else "",
            "prior_start_date": result.prior_start_date.isoformat() if result.prior_start_date else "",
            "prior_end_date": result.prior_end_date.isoformat() if result.prior_end_date else ""}

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


def export_prior_variance(*args, **kwargs):
    """Return the comparison as a list of dicts. Read-only."""
    return _rows(prior_variance_report(*args, **kwargs))


def export_prior_variance_csv(*args, **kwargs):
    """Return the comparison as a CSV string. Read-only."""
    result = prior_variance_report(*args, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PRIOR_VARIANCE_EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in _rows(result):
        writer.writerow(record)
    return buffer.getvalue()


prior_variance_csv = export_prior_variance_csv
export_prior_period_variance_csv = export_prior_variance_csv
export_prior_roster_variance = export_prior_variance
export_prior_roster_variance_csv = export_prior_variance_csv
