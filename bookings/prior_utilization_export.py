"""CSV export of the prior-period utilization comparison.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`bookings.prior_utilization` —
figures verbatim, never recomputed. First data row is the salon
total (staff fields empty), then one row per staff member in
``by_staff`` order. Utilization fractions render to four
places; percent changes to two places; ``None`` renders empty.
Lines end ``"\\n"``.
"""
import csv
import io

from bookings.prior_utilization import prior_utilization_report

__all__ = [
    "PRIOR_UTILIZATION_EXPORT_FIELDNAMES", "PRIOR_UTILIZATION_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_prior_utilization_csv",
    "prior_utilization_csv", "export_prior_period_utilization_csv",
]

PRIOR_UTILIZATION_EXPORT_FIELDNAMES = [
    "salon_id", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "staff_member_id", "staff_name",
    "current_appointment_count", "prior_appointment_count",
    "appointment_count_delta", "appointment_count_percent_change",
    "current_booked_minutes", "prior_booked_minutes",
    "booked_minutes_delta", "booked_minutes_percent_change",
    "current_rostered_minutes", "prior_rostered_minutes",
    "rostered_minutes_delta", "rostered_minutes_percent_change",
    "current_utilization", "prior_utilization",
    "utilization_delta", "utilization_percent_change",
]
PRIOR_UTILIZATION_FIELDNAMES = PRIOR_UTILIZATION_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_UTILIZATION_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def _util(value):
    return "" if value is None else f"{value:.4f}"


def export_prior_utilization_csv(salon, date_from=None, date_to=None, *,
                                 start_date=None, end_date=None, **kwargs):
    """Return the prior-period utilization comparison as CSV.

    Accepts exactly the parameters of
    :func:`bookings.prior_utilization.prior_utilization_report`,
    passed through unchanged (a reversed window raises
    ``ValueError`` from that service).
    """
    r = prior_utilization_report(
        salon, date_from, date_to, start_date=start_date,
        end_date=end_date, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_UTILIZATION_EXPORT_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()

    def _row(staff_id, staff_name, count, booked, rostered, util):
        writer.writerow({
            "salon_id": r.salon.pk if r.salon is not None else "",
            "current_start_date": r.start_date.isoformat() if r.start_date else "",
            "current_end_date": r.end_date.isoformat() if r.end_date else "",
            "prior_start_date": r.prior_start_date.isoformat() if r.prior_start_date else "",
            "prior_end_date": r.prior_end_date.isoformat() if r.prior_end_date else "",
            "staff_member_id": staff_id, "staff_name": staff_name,
            "current_appointment_count": count.current,
            "prior_appointment_count": count.prior,
            "appointment_count_delta": count.delta,
            "appointment_count_percent_change": _pct(count.percent_change),
            "current_booked_minutes": booked.current,
            "prior_booked_minutes": booked.prior,
            "booked_minutes_delta": booked.delta,
            "booked_minutes_percent_change": _pct(booked.percent_change),
            "current_rostered_minutes": rostered.current,
            "prior_rostered_minutes": rostered.prior,
            "rostered_minutes_delta": rostered.delta,
            "rostered_minutes_percent_change": _pct(rostered.percent_change),
            "current_utilization": _util(util.current),
            "prior_utilization": _util(util.prior),
            "utilization_delta": _util(util.delta),
            "utilization_percent_change": _pct(util.percent_change),
        })

    _row("", "", r.appointment_count, r.booked_minutes,
         r.rostered_minutes, r.utilization)
    for s in r.by_staff:
        _row(s.staff_member_id, s.staff_name, s.appointment_count,
             s.booked_minutes, s.rostered_minutes, s.utilization)
    return buffer.getvalue()


prior_utilization_csv = export_prior_utilization_csv
export_prior_period_utilization_csv = export_prior_utilization_csv
