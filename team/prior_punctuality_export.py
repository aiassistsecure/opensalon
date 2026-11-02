"""CSV export of the prior-period punctuality comparison.

Backend only — no views, templates, or UI. Read-only. Built ON
TOP of :mod:`team.prior_punctuality` — figures verbatim, never
recomputed. First row is the salon total (staff fields empty),
then one row per staff member in ``by_staff`` order. Counts are
ints; averages / percent changes render to two places, never
via a float; ``None`` renders empty. Lines ``\\n``.
"""
import csv
import io

from team.prior_punctuality import prior_punctuality_report

__all__ = ["PRIOR_PUNCTUALITY_EXPORT_FIELDNAMES", "PRIOR_PUNCTUALITY_FIELDNAMES",
           "EXPORT_FIELDNAMES", "export_prior_punctuality",
           "export_prior_punctuality_csv", "prior_punctuality_csv",
           "export_prior_period_punctuality_csv"]
_METRICS = ["shifts_considered", "on_time_count", "late_count", "missed_count",
            "total_late_minutes", "average_late_minutes"]
PRIOR_PUNCTUALITY_EXPORT_FIELDNAMES = (
    ["salon_id", "current_start_date", "current_end_date", "prior_start_date",
     "prior_end_date", "staff_member_id", "staff_name"]
    + [n for m in _METRICS for n in
       (f"current_{m}", f"prior_{m}", f"{m}_delta", f"{m}_percent_change")])
PRIOR_PUNCTUALITY_FIELDNAMES = PRIOR_PUNCTUALITY_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_PUNCTUALITY_EXPORT_FIELDNAMES


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
            avg = m == "average_late_minutes"
            row[f"current_{m}"] = _pct(d.current) if avg else d.current
            row[f"prior_{m}"] = _pct(d.prior) if avg else d.prior
            row[f"{m}_delta"] = _pct(d.delta) if avg else d.delta
            row[f"{m}_percent_change"] = _pct(d.percent_change)
        return row

    return [build("", "", result)] + [
        build(s.staff_member_id, s.staff_name, s) for s in result.by_staff]


def export_prior_punctuality(*args, **kwargs):
    """Return the comparison as a list of dicts. Read-only."""
    return _rows(prior_punctuality_report(*args, **kwargs))


def export_prior_punctuality_csv(*args, **kwargs):
    """Return the comparison as a CSV string. Read-only."""
    result = prior_punctuality_report(*args, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PRIOR_PUNCTUALITY_EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in _rows(result):
        writer.writerow(record)
    return buffer.getvalue()


prior_punctuality_csv = export_prior_punctuality_csv
export_prior_period_punctuality_csv = export_prior_punctuality_csv
