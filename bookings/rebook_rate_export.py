"""CSV export of the rebook rate summary.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the summary from
:mod:`bookings.rebook_rate` as CSV built ON TOP of
:func:`bookings.rebook_rate.rebook_rate_report` — counts and
rates are that service's verbatim; this module never recounts.
The first data row is the salon total (staff fields empty),
followed by one row per staff member in the service's
``by_staff`` order. Percentages render to two decimal places,
never via a float; a ``None`` rate (zero completed) renders
empty. Lines end ``"\\n"``.
"""
import csv
import io

from bookings.rebook_rate import rebook_rate_report

__all__ = [
    "REBOOK_RATE_EXPORT_FIELDNAMES",
    "export_rebook_rate_csv", "rebook_rate_csv",
]

REBOOK_RATE_EXPORT_FIELDNAMES = [
    "salon_id", "start_date", "end_date", "staff_member_id",
    "staff_name", "total_appointments", "completed", "rebooked",
    "rebook_rate_percent",
]


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def export_rebook_rate_csv(salon, date_from=None, date_to=None, *,
                           start_date=None, end_date=None):
    """Return the rebook rate summary as CSV.

    Accepts exactly the parameters of
    :func:`bookings.rebook_rate.rebook_rate_report`, passed
    through unchanged (a reversed window raises ``ValueError``
    from that service). One header row, the salon-total row,
    then one row per staff member with completed appointments.
    """
    r = rebook_rate_report(
        salon, date_from, date_to, start_date=start_date, end_date=end_date)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=REBOOK_RATE_EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()

    def _row(staff_member_id, staff_name, total, completed, rebooked, pct):
        writer.writerow({
            "salon_id": r.salon.pk if r.salon is not None else "",
            "start_date": r.start_date.isoformat() if r.start_date else "",
            "end_date": r.end_date.isoformat() if r.end_date else "",
            "staff_member_id": staff_member_id,
            "staff_name": staff_name,
            "total_appointments": total,
            "completed": completed,
            "rebooked": rebooked,
            "rebook_rate_percent": _pct(pct),
        })

    _row("", "", r.total_appointments, r.completed, r.rebooked,
         r.rebook_rate_percent)
    for s in r.by_staff:
        _row(s.staff_member_id, s.staff_name, "", s.completed, s.rebooked,
             s.rebook_rate_percent)
    return buffer.getvalue()


rebook_rate_csv = export_rebook_rate_csv
