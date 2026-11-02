"""CSV export of the prior-period online cancellations comparison.

Read-only. Founding rule (Exit Principle): renders
:mod:`onlinebooking.prior_cancellations` as dict rows and as
CSV built from that same list, so the formats never disagree;
every value comes verbatim from the service. Rows: one
``total`` row, then staff rows, then service rows. Columns:
window bounds, ``section``, staff/service identity,
``current`` / ``prior`` / ``delta`` / ``percent_change``
(empty when ``None``), and both window totals. Lines ``"\\n"``.
"""
import csv
import io
from decimal import Decimal

from .prior_cancellations import prior_cancellations

__all__ = ["EXPORT_FIELDNAMES", "PRIOR_CANCELLATIONS_FIELDNAMES",
           "export_prior_cancellations", "export_prior_cancellations_csv",
           "export_prior_cancellations_rows", "prior_cancellations_csv"]

EXPORT_FIELDNAMES = [
    "salon_id", "start_date", "end_date", "prior_start_date",
    "prior_end_date", "section", "staff_member_id", "staff_name",
    "service_id", "service_name", "current", "prior", "delta",
    "percent_change", "current_total", "prior_total",
]
PRIOR_CANCELLATIONS_FIELDNAMES = EXPORT_FIELDNAMES
_CENTS = Decimal("0.01")


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _row(result, section, delta, staff_id=None, staff_name=None,
         service_id=None, service_name=None):
    return {
        "salon_id": result.salon_id,
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat(),
        "prior_start_date": result.prior_start_date.isoformat(),
        "prior_end_date": result.prior_end_date.isoformat(),
        "section": section, "staff_member_id": staff_id,
        "staff_name": staff_name, "service_id": service_id,
        "service_name": service_name, "current": delta.current,
        "prior": delta.prior, "delta": delta.delta,
        "percent_change": _pct(delta.percent_change),
        "current_total": result.current.total,
        "prior_total": result.prior.total}


def export_prior_cancellations(salon, start=None, end=None, **kwargs):
    """Return the prior cancellations comparison as dict rows."""
    result = prior_cancellations(salon, start, end, **kwargs)
    rows = [_row(result, "total", result.total)]
    rows += [_row(result, "staff", r, staff_id=r.staff_member_id,
                  staff_name=r.staff_name) for r in result.by_staff]
    rows += [_row(result, "service", r, service_id=r.service_id,
                  service_name=r.service_name) for r in result.by_service]
    return rows


def export_prior_cancellations_csv(salon, start=None, end=None, **kwargs):
    """Return :func:`export_prior_cancellations` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in export_prior_cancellations(salon, start, end, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


export_prior_cancellations_rows = export_prior_cancellations
prior_cancellations_csv = export_prior_cancellations_csv
