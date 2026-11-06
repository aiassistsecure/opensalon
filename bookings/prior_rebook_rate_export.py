"""CSV + dict export of the prior-period rebook rate comparison.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`bookings.prior_rebook_rate` —
figures verbatim, never recounted. First data row is the salon
total (staff fields empty), then one row per staff member in
``by_staff`` order. The CSV is built from the dict rows
(:func:`export_prior_rebook_rate_rows`): keys are
:data:`PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES` in order, counts are
ints, rates / percent changes render to two places as strings,
never via a float; ``None`` renders as ``""`` (exactly as in the
CSV). Lines ``\\n``.
"""
import csv
import io

from bookings.prior_rebook_rate import prior_rebook_rate_report

__all__ = [
    "PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES", "PRIOR_REBOOK_RATE_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_prior_rebook_rate_csv",
    "prior_rebook_rate_csv", "export_prior_period_rebook_rate_csv",
    "export_prior_rebook_rate_rows", "prior_rebook_rate_rows",
    "export_prior_rebook_rate", "export_prior_rebook_rate_dict",
    "prior_rebook_rate_dict",
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


def export_prior_rebook_rate_rows(salon, date_from=None, date_to=None, *,
                                  start_date=None, end_date=None, **kwargs):
    """Return the prior-period rebook rate comparison as dict rows.

    Accepts exactly the parameters of
    :func:`bookings.prior_rebook_rate.prior_rebook_rate_report`,
    passed through unchanged (a reversed window raises
    ``ValueError`` from that service). The dicts mirror the CSV
    rows exactly: keys are
    :data:`PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES` in order, with
    the CSV rendering applied (percentages as two-place strings,
    ``None`` as ``""``). First row is the salon total, then one
    row per staff member in ``by_staff`` order.
    """
    r = prior_rebook_rate_report(
        salon, date_from, date_to, start_date=start_date,
        end_date=end_date, **kwargs)

    def _row(staff_id, staff_name, completed, rebooked, rate):
        return {
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
        }

    rows = [_row("", "", r.completed, r.rebooked, r.rebook_rate_percent)]
    for s in r.by_staff:
        rows.append(_row(s.staff_member_id, s.staff_name, s.completed,
                         s.rebooked, s.rebook_rate_percent))
    return rows


def export_prior_rebook_rate_csv(salon, date_from=None, date_to=None, *,
                                 start_date=None, end_date=None, **kwargs):
    """Return the prior-period rebook rate comparison as CSV.

    Built from :func:`export_prior_rebook_rate_rows` with the same
    arguments, so the CSV and dict exports always agree and the
    historical CSV output is byte-identical.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()
    for row in export_prior_rebook_rate_rows(
            salon, date_from, date_to, start_date=start_date,
            end_date=end_date, **kwargs):
        writer.writerow(row)
    return buffer.getvalue()


prior_rebook_rate_csv = export_prior_rebook_rate_csv
export_prior_period_rebook_rate_csv = export_prior_rebook_rate_csv
prior_rebook_rate_rows = export_prior_rebook_rate_rows
export_prior_rebook_rate = export_prior_rebook_rate_rows
export_prior_rebook_rate_dict = export_prior_rebook_rate_rows
prior_rebook_rate_dict = export_prior_rebook_rate_rows
