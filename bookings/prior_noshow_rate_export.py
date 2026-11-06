"""CSV + dict export of the prior-period no-show comparison.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`bookings.prior_noshow_rate` —
figures verbatim, never recounted. One summary row for the salon.
The CSV is built from the one dict row
(:func:`export_prior_noshow_rate_row`): keys are
:data:`PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES` in order, counts are
ints, rates / percent changes render to two places as strings,
never via a float; ``None`` renders as ``""`` (exactly as in the
CSV). Lines ``\\n``.
"""
import csv
import io

from bookings.prior_noshow_rate import prior_noshow_rate_report

__all__ = [
    "PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES", "PRIOR_NOSHOW_RATE_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_prior_noshow_rate_csv",
    "prior_noshow_rate_csv", "export_prior_period_noshow_rate_csv",
    "export_prior_noshow_rate_row", "prior_noshow_rate_row",
    "export_prior_noshow_rate_rows", "prior_noshow_rate_rows",
    "export_prior_noshow_rate", "export_prior_noshow_rate_dict",
    "prior_noshow_rate_dict",
]

PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES = [
    "salon_id", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date",
    "current_total_appointments", "prior_total_appointments",
    "total_appointments_delta", "total_appointments_percent_change",
    "current_completed", "prior_completed", "completed_delta",
    "completed_percent_change",
    "current_no_shows", "prior_no_shows", "no_shows_delta",
    "no_shows_percent_change",
    "current_cancelled", "prior_cancelled", "cancelled_delta",
    "cancelled_percent_change",
    "current_late_cancellations", "prior_late_cancellations",
    "late_cancellations_delta", "late_cancellations_percent_change",
    "current_no_show_rate_percent", "prior_no_show_rate_percent",
    "no_show_rate_delta", "no_show_rate_percent_change",
    "current_late_cancel_rate_percent", "prior_late_cancel_rate_percent",
    "late_cancel_rate_delta", "late_cancel_rate_percent_change",
]
PRIOR_NOSHOW_RATE_FIELDNAMES = PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def export_prior_noshow_rate_row(salon, date_from=None, date_to=None, *,
                                 start_date=None, end_date=None, **kwargs):
    """Return the prior-period no-show comparison as one dict row.

    Accepts exactly the parameters of
    :func:`bookings.prior_noshow_rate.prior_noshow_rate_report`,
    passed through unchanged (a reversed window raises
    ``ValueError`` from that service). The dict mirrors the CSV
    row exactly: keys are
    :data:`PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES` in order, with
    the CSV rendering applied (percentages as two-place strings,
    ``None`` as ``""``).
    """
    r = prior_noshow_rate_report(
        salon, date_from, date_to, start_date=start_date,
        end_date=end_date, **kwargs)

    def _m(metric, prefix):
        return {f"current_{prefix}": metric.current, f"prior_{prefix}": metric.prior,
                f"{prefix}_delta": metric.delta,
                f"{prefix}_percent_change": _pct(metric.percent_change)}

    def _r(metric, prefix, stem):
        return {f"current_{prefix}": _pct(metric.current),
                f"prior_{prefix}": _pct(metric.prior),
                f"{stem}_delta": _pct(metric.delta),
                f"{stem}_percent_change": _pct(metric.percent_change)}

    row = {
        "salon_id": r.salon.pk if r.salon is not None else "",
        "current_start_date": r.start_date.isoformat() if r.start_date else "",
        "current_end_date": r.end_date.isoformat() if r.end_date else "",
        "prior_start_date": r.prior_start_date.isoformat() if r.prior_start_date else "",
        "prior_end_date": r.prior_end_date.isoformat() if r.prior_end_date else "",
    }
    for metric, prefix in [(r.total_appointments, "total_appointments"),
                           (r.completed, "completed"), (r.no_shows, "no_shows"),
                           (r.cancelled, "cancelled"),
                           (r.late_cancellations, "late_cancellations")]:
        row.update(_m(metric, prefix))
    row.update(_r(r.no_show_rate_percent, "no_show_rate_percent", "no_show_rate"))
    row.update(_r(r.late_cancel_rate_percent, "late_cancel_rate_percent", "late_cancel_rate"))
    return row


def export_prior_noshow_rate_rows(salon, date_from=None, date_to=None, *,
                                  start_date=None, end_date=None, **kwargs):
    """Return the comparison as a list holding the one dict row."""
    return [export_prior_noshow_rate_row(
        salon, date_from, date_to, start_date=start_date,
        end_date=end_date, **kwargs)]


def export_prior_noshow_rate_csv(salon, date_from=None, date_to=None, *,
                                 start_date=None, end_date=None, **kwargs):
    """Return the prior-period no-show comparison as CSV.

    Built from :func:`export_prior_noshow_rate_row` with the same
    arguments, so the CSV and dict exports always agree and the
    historical CSV output is byte-identical.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_NOSHOW_RATE_EXPORT_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()
    writer.writerow(export_prior_noshow_rate_row(
        salon, date_from, date_to, start_date=start_date,
        end_date=end_date, **kwargs))
    return buffer.getvalue()


prior_noshow_rate_csv = export_prior_noshow_rate_csv
export_prior_period_noshow_rate_csv = export_prior_noshow_rate_csv
prior_noshow_rate_row = export_prior_noshow_rate_row
prior_noshow_rate_rows = export_prior_noshow_rate_rows
export_prior_noshow_rate = export_prior_noshow_rate_rows
export_prior_noshow_rate_dict = export_prior_noshow_rate_rows
prior_noshow_rate_dict = export_prior_noshow_rate_rows
