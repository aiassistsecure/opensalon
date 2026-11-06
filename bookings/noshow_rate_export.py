"""CSV export of the no-show / late-cancel rate summary.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the summary from
:mod:`bookings.noshow_rate` as a single-row CSV built ON TOP of
:func:`bookings.noshow_rate.noshow_rate_report` — counts and
rates are that service's verbatim; this module never recounts.
Percentages render to two decimal places, never via a float;
a ``None`` rate (zero total) renders empty. Lines end ``"\\n"``.

A plain dict row (:func:`export_noshow_rate_row`) backs the
CSV, so the two formats can never disagree.
"""
import csv
import io

from bookings.noshow_rate import noshow_rate_report

__all__ = [
    "NOSHOW_RATE_EXPORT_FIELDNAMES",
    "export_noshow_rate_csv", "noshow_rate_csv",
    "export_noshow_rate_row", "noshow_rate_row",
]

NOSHOW_RATE_EXPORT_FIELDNAMES = [
    "salon_id", "start_date", "end_date", "total_appointments",
    "completed", "no_shows", "cancelled", "late_cancellations",
    "no_show_rate_percent", "late_cancel_rate_percent",
]


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def export_noshow_rate_row(salon, date_from=None, date_to=None, *,
                           start_date=None, end_date=None):
    """Return the no-show / late-cancel rate summary as one dict row.

    Accepts exactly the parameters of
    :func:`bookings.noshow_rate.noshow_rate_report`, passed
    through unchanged. The dict has exactly
    :data:`NOSHOW_RATE_EXPORT_FIELDNAMES` keys, in order, with
    the CSV rendering applied (percentages as two-place strings,
    ``None`` rates as ``""``).
    """
    r = noshow_rate_report(
        salon, date_from, date_to, start_date=start_date, end_date=end_date)
    return {
        "salon_id": r.salon.pk if r.salon is not None else "",
        "start_date": r.start_date.isoformat() if r.start_date else "",
        "end_date": r.end_date.isoformat() if r.end_date else "",
        "total_appointments": r.total_appointments,
        "completed": r.completed,
        "no_shows": r.no_shows,
        "cancelled": r.cancelled,
        "late_cancellations": r.late_cancellations,
        "no_show_rate_percent": _pct(r.no_show_rate_percent),
        "late_cancel_rate_percent": _pct(r.late_cancel_rate_percent),
    }


def export_noshow_rate_csv(salon, date_from=None, date_to=None, *,
                           start_date=None, end_date=None):
    """Return the no-show / late-cancel rate summary as CSV.

    Built from :func:`export_noshow_rate_row` with the same
    arguments (one header row plus one summary row), so CSV
    and JSON can never disagree. A reversed window raises
    ``ValueError`` from the underlying service.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=NOSHOW_RATE_EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    writer.writerow(export_noshow_rate_row(
        salon, date_from, date_to, start_date=start_date, end_date=end_date))
    return buffer.getvalue()


noshow_rate_csv = export_noshow_rate_csv
noshow_rate_row = export_noshow_rate_row
