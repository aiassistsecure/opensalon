"""CSV + dict export of the rebook rate summary.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the summary from
:mod:`bookings.rebook_rate` as CSV built ON TOP of
:func:`bookings.rebook_rate.rebook_rate_report` — counts and
rates are that service's verbatim; this module never recounts.
The first data row is the salon total (staff fields empty),
followed by one row per staff member in the service's
``by_staff`` order. The CSV is built from the dict rows
(:func:`export_rebook_rate_rows`): keys are
:data:`REBOOK_RATE_EXPORT_FIELDNAMES` in order, counts are
ints, percentages render to two decimal places as strings,
never via a float; a ``None`` rate (zero completed) renders
empty (``""``, exactly as in the CSV). Per-staff rows carry
``""`` for ``total_appointments``, exactly as in the CSV.
Lines end ``"\\n"``.
"""
import csv
import io

from bookings.rebook_rate import rebook_rate_report

__all__ = [
    "REBOOK_RATE_EXPORT_FIELDNAMES", "REBOOK_RATE_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_rebook_rate_csv", "rebook_rate_csv",
    "export_rebook_rate_rows", "rebook_rate_rows",
    "export_rebook_rate", "export_rebook_rate_dict",
    "rebook_rate_dict",
]

REBOOK_RATE_EXPORT_FIELDNAMES = [
    "salon_id", "start_date", "end_date", "staff_member_id",
    "staff_name", "total_appointments", "completed", "rebooked",
    "rebook_rate_percent",
]
REBOOK_RATE_FIELDNAMES = REBOOK_RATE_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = REBOOK_RATE_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def export_rebook_rate_rows(salon, date_from=None, date_to=None, *,
                            start_date=None, end_date=None):
    """Return the rebook rate summary as dict rows.

    Accepts exactly the parameters of
    :func:`bookings.rebook_rate.rebook_rate_report`, passed
    through unchanged (a reversed window raises ``ValueError``
    from that service). The dicts mirror the CSV rows exactly:
    keys are :data:`REBOOK_RATE_EXPORT_FIELDNAMES` in order,
    with the CSV rendering applied (percentages as two-place
    strings, ``None`` as ``""``). First row is the salon total,
    then one row per staff member in ``by_staff`` order.
    """
    r = rebook_rate_report(
        salon, date_from, date_to, start_date=start_date, end_date=end_date)

    def _row(staff_member_id, staff_name, total, completed, rebooked, pct):
        return {
            "salon_id": r.salon.pk if r.salon is not None else "",
            "start_date": r.start_date.isoformat() if r.start_date else "",
            "end_date": r.end_date.isoformat() if r.end_date else "",
            "staff_member_id": staff_member_id,
            "staff_name": staff_name,
            "total_appointments": total,
            "completed": completed,
            "rebooked": rebooked,
            "rebook_rate_percent": _pct(pct),
        }

    rows = [_row("", "", r.total_appointments, r.completed, r.rebooked,
                 r.rebook_rate_percent)]
    for s in r.by_staff:
        rows.append(_row(s.staff_member_id, s.staff_name, "", s.completed,
                         s.rebooked, s.rebook_rate_percent))
    return rows


def export_rebook_rate_csv(salon, date_from=None, date_to=None, *,
                           start_date=None, end_date=None):
    """Return the rebook rate summary as CSV.

    Built from :func:`export_rebook_rate_rows` with the same
    arguments, so the CSV and dict exports always agree and the
    historical CSV output is byte-identical. One header row, the
    salon-total row, then one row per staff member with
    completed appointments.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=REBOOK_RATE_EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for row in export_rebook_rate_rows(
            salon, date_from, date_to, start_date=start_date,
            end_date=end_date):
        writer.writerow(row)
    return buffer.getvalue()


rebook_rate_csv = export_rebook_rate_csv
rebook_rate_rows = export_rebook_rate_rows
export_rebook_rate = export_rebook_rate_rows
export_rebook_rate_dict = export_rebook_rate_rows
rebook_rate_dict = export_rebook_rate_rows
