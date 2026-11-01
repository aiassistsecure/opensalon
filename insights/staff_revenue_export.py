"""Per-staff revenue CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale, appointment,
or staff member.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's per-staff revenue
report as a CSV string built ON TOP of
:mod:`insights.staff_revenue` — the definition of per-staff
revenue (completed sales only, effective-date window, salon
scoping, and the documented sale-level attribution heuristic in
that module, including its unattributed bucket) is that
service's alone and is reused verbatim via
:func:`insights.staff_revenue.revenue_by_staff`; this module
never reimplements attribution, re-queries sales, or re-orders
rows. Ordering is exactly the service's ordering: ``total``
descending, then ``display_name`` ascending.

Columns are only fields the service's rows actually carry:

- ``staff_name``: the row's ``display_name`` — the staff
  member's display name, or ``"Unattributed"`` for the
  service's unattributed bucket (``staff is None``), which
  appears as a row exactly as the service returns it.
- ``service_revenue``: the row's service revenue.
- ``retail_revenue``: the row's retail (product) revenue.
- ``series_revenue``: the row's series revenue.
- ``total``: the row's total revenue.

Money is rendered as a string to two decimal places, never
passed through a float.
"""
import csv
import io
from decimal import Decimal

from insights.staff_revenue import revenue_by_staff

__all__ = [
    "STAFF_REVENUE_FIELDNAMES",
    "STAFF_REVENUE_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_staff_revenue_csv",
    "staff_revenue_csv",
]

#: Column order of the CSV export.
STAFF_REVENUE_FIELDNAMES = [
    "staff_name",
    "service_revenue",
    "retail_revenue",
    "series_revenue",
    "total",
]

STAFF_REVENUE_EXPORT_FIELDNAMES = STAFF_REVENUE_FIELDNAMES
EXPORT_FIELDNAMES = STAFF_REVENUE_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_staff_revenue_csv(salon, start, end, **kwargs):
    """Return ``salon``'s per-staff revenue report as a CSV string.

    Args:
        salon: ``saloncore.Salon`` instance to scope to, passed
            through to
            :func:`insights.staff_revenue.revenue_by_staff`.
        start: inclusive window start, as accepted by that service.
        end: inclusive window end, as accepted by that service.
        **kwargs: forwarded to that service.

    Returns:
        A CSV string whose header row is
        :data:`STAFF_REVENUE_FIELDNAMES` and whose data rows
        follow the staff-revenue service's ordering exactly,
        with values matching that service's rows, including the
        ``Unattributed`` bucket row when the service returns
        one. An empty window exports as the header row alone.
        Lines end with ``"\\n"``.
    """
    rows = revenue_by_staff(salon, start, end, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=STAFF_REVENUE_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "staff_name": row.display_name,
            "service_revenue": _money(row.service_revenue),
            "retail_revenue": _money(row.retail_revenue),
            "series_revenue": _money(row.series_revenue),
            "total": _money(row.total),
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
staff_revenue_csv = export_staff_revenue_csv
