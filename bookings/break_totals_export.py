"""Paid/unpaid break totals dict/CSV export.

Backend only, read-only (Exit Principle: anything a salon can
enter, it can fully export). Built ON TOP of
:mod:`bookings.break_totals` — totals, scoping, split, and
ordering are that service's alone, reused verbatim; this
module never re-queries ``Break`` rows. One row per staff
member in the service's ``by_staff``: scope columns
(``salon_id``, ``start_date``, ``end_date``), staff id/name,
then break_count/total_break_minutes, paid and unpaid counts
and minutes. Empty range = header row alone. Lines end "\n".
"""
import csv
import io

from bookings.break_totals import break_totals

__all__ = [
    "BREAK_TOTALS_EXPORT_FIELDNAMES",
    "break_totals_csv",
    "break_totals_rows",
    "export_break_totals_csv",
]

BREAK_TOTALS_EXPORT_FIELDNAMES = [
    "salon_id",
    "start_date",
    "end_date",
    "staff_member_id",
    "staff_name",
    "break_count",
    "total_break_minutes",
    "paid_break_count",
    "paid_minutes",
    "unpaid_break_count",
    "unpaid_minutes",
]


def break_totals_rows(salon, date_from, date_to=None, *, staff_member=None):
    """Return per-staff break totals as plain dicts.

    Accepts exactly the parameters of
    :func:`bookings.break_totals.break_totals`, passed through
    unchanged. Each dict has exactly
    :data:`BREAK_TOTALS_EXPORT_FIELDNAMES` keys.
    """
    report = break_totals(salon, date_from, date_to, staff_member=staff_member)
    scope = {
        "salon_id": salon.pk if salon is not None else None,
        "start_date": report.start_date.isoformat() if report.start_date else None,
        "end_date": report.end_date.isoformat() if report.end_date else None,
    }
    return [{**scope, **row.as_dict()} for row in report.by_staff]


def export_break_totals_csv(salon, date_from, date_to=None, *, staff_member=None):
    """Return per-staff break totals for ``salon`` as a CSV string."""
    rows = break_totals_rows(salon, date_from, date_to, staff_member=staff_member)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=BREAK_TOTALS_EXPORT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            name: ("" if row[name] is None else row[name])
            for name in BREAK_TOTALS_EXPORT_FIELDNAMES
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
break_totals_csv = export_break_totals_csv
