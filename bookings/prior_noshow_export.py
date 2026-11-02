"""CSV + dict export of the prior-period no-show comparison.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Built ON TOP of :mod:`bookings.prior_noshow` — figures
verbatim, never recounted. The CSV is built from the one dict
list (:func:`prior_noshow_rows`): first row is the salon total
(``section="total"``), then one row per staff member
(``section="staff"``) in ``by_staff`` order, then one row per
client (``section="client"``) in ``by_client`` order. Rates
render to four places, percent changes to two; ``None`` renders
empty in CSV. Lines end ``"\\n"``. No client contact details.
"""
import csv
import io

from bookings.prior_noshow import prior_noshow_report

__all__ = ["PRIOR_NOSHOW_EXPORT_FIELDNAMES", "PRIOR_NOSHOW_FIELDNAMES",
           "EXPORT_FIELDNAMES", "prior_noshow_rows",
           "export_prior_noshow_rows", "export_prior_noshow_dict",
           "prior_noshow_dict", "export_prior_noshow_csv",
           "prior_noshow_csv", "export_prior_period_noshow_csv"]

PRIOR_NOSHOW_EXPORT_FIELDNAMES = [
    "salon_id", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "section",
    "staff_member_id", "staff_name", "client_id", "client_name",
    "current_no_show_count", "prior_no_show_count",
    "no_show_count_delta", "no_show_count_percent_change",
    "current_denominator", "prior_denominator",
    "denominator_delta", "denominator_percent_change",
    "current_rate", "prior_rate", "rate_delta", "rate_percent_change",
]
PRIOR_NOSHOW_FIELDNAMES = PRIOR_NOSHOW_EXPORT_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_NOSHOW_EXPORT_FIELDNAMES

def _pct(value):
    return "" if value is None else f"{value:.2f}"

def _rate(value):
    return "" if value is None else f"{value:.4f}"

def _flat(report, section, staff_id, staff_name, client_id, client_name, source):
    return {
        "salon_id": report.salon.pk if report.salon is not None else "",
        "current_start_date": report.start_date.isoformat() if report.start_date else "",
        "current_end_date": report.end_date.isoformat() if report.end_date else "",
        "prior_start_date": report.prior_start_date.isoformat() if report.prior_start_date else "",
        "prior_end_date": report.prior_end_date.isoformat() if report.prior_end_date else "",
        "section": section, "staff_member_id": staff_id, "staff_name": staff_name,
        "client_id": client_id, "client_name": client_name,
        "current_no_show_count": source.no_show_count.current,
        "prior_no_show_count": source.no_show_count.prior,
        "no_show_count_delta": source.no_show_count.delta,
        "no_show_count_percent_change": source.no_show_count.percent_change,
        "current_denominator": source.denominator.current,
        "prior_denominator": source.denominator.prior,
        "denominator_delta": source.denominator.delta,
        "denominator_percent_change": source.denominator.percent_change,
        "current_rate": source.rate.current, "prior_rate": source.rate.prior,
        "rate_delta": source.rate.delta,
        "rate_percent_change": source.rate.percent_change,
    }

def prior_noshow_rows(salon, date_from=None, date_to=None, **kwargs):
    """Return the comparison as a list of plain dicts.

    First entry is the salon total, then staff rows, then client
    rows. This one list is the source for the CSV export.
    Accepts the parameters of :func:`prior_noshow_report`.
    """
    r = prior_noshow_report(salon, date_from, date_to, **kwargs)
    return ([_flat(r, "total", "", "", "", "", r)]
            + [_flat(r, "staff", s.staff_member_id, s.staff_name, "", "", s)
               for s in r.by_staff]
            + [_flat(r, "client", "", "", c.client_id, c.client_name, c)
               for c in r.by_client])

export_prior_noshow_rows = prior_noshow_rows
export_prior_noshow_dict = prior_noshow_rows
prior_noshow_dict = prior_noshow_rows

def export_prior_noshow_csv(salon, date_from=None, date_to=None, **kwargs):
    """Return the comparison as CSV, built from the dict list."""
    rows = prior_noshow_rows(salon, date_from, date_to, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=PRIOR_NOSHOW_EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            **row,
            "no_show_count_percent_change": _pct(row["no_show_count_percent_change"]),
            "denominator_percent_change": _pct(row["denominator_percent_change"]),
            "current_rate": _rate(row["current_rate"]),
            "prior_rate": _rate(row["prior_rate"]),
            "rate_delta": _rate(row["rate_delta"]),
            "rate_percent_change": _pct(row["rate_percent_change"]),
        })
    return buffer.getvalue()

prior_noshow_csv = export_prior_noshow_csv
export_prior_period_noshow_csv = export_prior_noshow_csv
