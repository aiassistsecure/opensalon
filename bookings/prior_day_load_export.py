"""CSV + dict export of the prior (same-weekday) day load.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`bookings.prior_day_load` —
figures verbatim, never recounted. First data row is the salon
total (staff fields empty), then one row per staff member in
``by_staff`` order. Percent changes render to two places;
``None`` renders empty in CSV; times render ISO-8601 or empty.
Lines end ``"\\n"``.
"""
import csv
import io

from bookings.prior_day_load import METRICS, TIME_FIELDS, prior_day_load_report

__all__ = ["PRIOR_DAY_LOAD_EXPORT_FIELDNAMES", "PRIOR_DAY_LOAD_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_prior_day_load_csv", "prior_day_load_csv",
    "export_prior_same_weekday_day_load_csv", "export_prior_day_load_dict",
    "prior_day_load_dict", "export_prior_same_weekday_day_load_dict"]

PRIOR_DAY_LOAD_EXPORT_FIELDNAMES = [
    "salon_id", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "staff_member_id", "staff_name",
]
for _m in METRICS:
    PRIOR_DAY_LOAD_EXPORT_FIELDNAMES += [
        f"current_{_m}", f"prior_{_m}", f"{_m}_delta",
        f"{_m}_percent_change"]
for _p in ("current", "prior"):
    PRIOR_DAY_LOAD_EXPORT_FIELDNAMES += [f"{_p}_{_f}" for _f in TIME_FIELDS]
PRIOR_DAY_LOAD_FIELDNAMES = PRIOR_DAY_LOAD_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_DAY_LOAD_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def _iso(value):
    return value.isoformat() if value else ""


def _flat(report, staff_id, staff_name, source):
    row = {"salon_id": report.salon.pk if report.salon is not None else "",
        "current_start_date": report.date.isoformat() if report.date else "",
        "current_end_date": report.date.isoformat() if report.date else "",
        "prior_start_date": report.prior_date.isoformat() if report.prior_date else "",
        "prior_end_date": report.prior_date.isoformat() if report.prior_date else "",
        "staff_member_id": staff_id, "staff_name": staff_name}
    for m in METRICS:
        d = getattr(source, m)
        row[f"current_{m}"] = d.current
        row[f"prior_{m}"] = d.prior
        row[f"{m}_delta"] = d.delta
        row[f"{m}_percent_change"] = d.percent_change
    for p in ("current", "prior"):
        for f in TIME_FIELDS:
            row[f"{p}_{f}"] = getattr(source, f"{p}_{f}")
    return row


def _rows(report):
    return [_flat(report, "", "", report)] + [
        _flat(report, s.staff_member_id, s.staff_name, s)
        for s in report.by_staff]


def export_prior_day_load_dict(salon, day=None, **kwargs):
    """Return the comparison as plain dicts (total + per-staff rows)."""
    r = prior_day_load_report(salon, day, **kwargs)
    return {"salon_id": r.salon.pk if r.salon is not None else None,
            **r.as_dict(), "rows": _rows(r)}


def export_prior_day_load_csv(salon, day=None, **kwargs):
    """Return the comparison as CSV (params pass through unchanged)."""
    r = prior_day_load_report(salon, day, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_DAY_LOAD_EXPORT_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()
    for row in _rows(r):
        writer.writerow({
            **row,
            **{f"{m}_percent_change": _pct(row[f"{m}_percent_change"])
               for m in METRICS},
            **{f"{p}_{f}": _iso(row[f"{p}_{f}"])
               for p in ("current", "prior") for f in TIME_FIELDS},
        })
    return buffer.getvalue()


prior_day_load_csv = export_prior_day_load_csv
export_prior_same_weekday_day_load_csv = export_prior_day_load_csv
prior_day_load_dict = export_prior_day_load_dict
export_prior_same_weekday_day_load_dict = export_prior_day_load_dict
