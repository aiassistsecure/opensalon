"""CSV export of the prior-period rebook rate comparison.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`bookings.prior_rebook_rate` —
figures verbatim, never recounted. First data row is the salon
total (staff fields empty), then one row per staff member in
``by_staff`` order. Rates / percent changes render to two
places, never via a float; ``None`` renders empty. Lines ``\\n``.
"""
import csv
import io

from bookings.prior_rebook_rate import prior_rebook_rate_report

__all__ = [
    "PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES", "PRIOR_REBOOK_RATE_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_prior_rebook_rate_csv",
    "prior_rebook_rate_csv", "export_prior_period_rebook_rate_csv",
]

PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES = [
    "salon_id", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "staff_member_id", "staff_name",
    "current_completed", "prior_completed", "completed_delta",
    "completed_percent_change", "current_rebooked", "prior_rebooked",
    "rebooked_delta", "rebooked_percent_change",
    "current_rebook_rate_percent", "prior_rebook_rate_percent",
    "rebook_rate_delta", "rebook_rate_percent_change",
]
PRIOR_REBOOK_RATE_FIELDNAMES = PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES


def _pct(value):
    return "" if value is None else f"{value:.2f}"


def export_prior_rebook_rate_csv(salon, date_from=None, date_to=None, *,
                                 start_date=None, end_date=None, **kwargs):
    """Return the prior-period rebook rate comparison as CSV.

    Accepts exactly the parameters of
    :func:`bookings.prior_rebook_rate.prior_rebook_rate_report`,
    passed through unchanged (a reversed window raises
    ``ValueError`` from that service).
    """
    r = prior_rebook_rate_report(
        salon, date_from, date_to, start_date=start_date,
        end_date=end_date, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()

    def _row(staff_id, staff_name, completed, rebooked, rate):
        writer.writerow({
            "salon_id": r.salon.pk if r.salon is not None else "",
            "current_start_date": r.start_date.isoformat() if r.start_date else "",
            "current_end_date": r.end_date.isoformat() if r.end_date else "",
            "prior_start_date": r.prior_start_date.isoformat() if r.prior_start_date else "",
            "prior_end_date": r.prior_end_date.isoformat() if r.prior_end_date else "",
            "staff_member_id": staff_id, "staff_name": staff_name,
            "current_completed": completed.current,
            "prior_completed": completed.prior,
            "completed_delta": completed.delta,
            "completed_percent_change": _pct(completed.percent_change),
            "current_rebooked": rebooked.current,
            "prior_rebooked": rebooked.prior,
            "rebooked_delta": rebooked.delta,
            "rebooked_percent_change": _pct(rebooked.percent_change),
            "current_rebook_rate_percent": _pct(rate.current),
            "prior_rebook_rate_percent": _pct(rate.prior),
            "rebook_rate_delta": _pct(rate.delta),
            "rebook_rate_percent_change": _pct(rate.percent_change),
        })

    _row("", "", r.completed, r.rebooked, r.rebook_rate_percent)
    for s in r.by_staff:
        _row(s.staff_member_id, s.staff_name, s.completed, s.rebooked,
             s.rebook_rate_percent)
    return buffer.getvalue()


prior_rebook_rate_csv = export_prior_rebook_rate_csv
export_prior_period_rebook_rate_csv = export_prior_rebook_rate_csv
