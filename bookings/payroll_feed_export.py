"""Combined payroll feed dict/CSV export.

Backend only, read-only. Built ON TOP of
:mod:`bookings.payroll_feed` — roster, attendance, and break
figures are that service's alone; this module never re-queries
roster, attendance, or break rows. One row per staff member in
the service's ``by_staff``. Empty salon/range = header alone.
Lines end "\\n".
"""
import csv
import io

from bookings.payroll_feed import payroll_feed

__all__ = [
    "PAYROLL_FEED_EXPORT_FIELDNAMES",
    "export_payroll_feed_csv",
    "payroll_feed_csv",
    "payroll_feed_rows",
]

PAYROLL_FEED_EXPORT_FIELDNAMES = [
    "salon_id", "start_date", "end_date", "staff_member_id", "staff_name",
    "rostered_minutes", "rostered_days", "rostered_intervals",
    "actual_minutes", "attendance_sessions", "closed_sessions",
    "open_sessions", "break_count", "total_break_minutes",
    "paid_break_count", "paid_minutes", "unpaid_break_count",
    "unpaid_minutes",
]


def payroll_feed_rows(salon, start_date, end_date=None, *, staff_member=None):
    """Return per-staff payroll feed rows as plain dicts."""
    report = payroll_feed(salon, start_date, end_date, staff_member=staff_member)
    scope = {
        "salon_id": salon.pk if salon is not None else None,
        "start_date": report.start_date.isoformat() if report.start_date else None,
        "end_date": report.end_date.isoformat() if report.end_date else None,
    }
    return [{**scope, **row.as_dict()} for row in report.by_staff]


def export_payroll_feed_csv(salon, start_date, end_date=None, *, staff_member=None):
    """Return the per-staff payroll feed for ``salon`` as a CSV string."""
    rows = payroll_feed_rows(salon, start_date, end_date, staff_member=staff_member)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PAYROLL_FEED_EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            name: ("" if row[name] is None else row[name])
            for name in PAYROLL_FEED_EXPORT_FIELDNAMES
        })
    return buffer.getvalue()


payroll_feed_csv = export_payroll_feed_csv
