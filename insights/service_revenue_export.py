"""Per-service revenue CSV export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. Built ON TOP of :mod:`insights.service_revenue` via
:func:`insights.service_revenue.revenue_by_service` — that service's
definition (completed service items only, window, grouping,
ranking, revenue per hour) is reused verbatim; this module never
reimplements it or re-orders rows. Columns are only fields the
rows carry; ``service_id`` and duration fields are empty for
snapshot-only rows, and ``revenue_per_hour`` is empty when the
row's is ``None``. Money renders to two decimal places, never
through a float.
"""
import csv
import io
from decimal import Decimal

from insights.service_revenue import revenue_by_service

__all__ = [
    "SERVICE_REVENUE_FIELDNAMES",
    "SERVICE_REVENUE_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_service_revenue_csv",
    "service_revenue_csv",
]

SERVICE_REVENUE_FIELDNAMES = [
    "service_id",
    "service_name",
    "revenue",
    "quantity",
    "line_count",
    "sale_count",
    "duration_minutes",
    "total_duration_minutes",
    "revenue_per_hour",
]

SERVICE_REVENUE_EXPORT_FIELDNAMES = SERVICE_REVENUE_FIELDNAMES
EXPORT_FIELDNAMES = SERVICE_REVENUE_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _int_or_empty(value):
    return "" if value is None else value


def export_service_revenue_csv(salon, start, end, **kwargs):
    """Return ``salon``'s per-service revenue report as CSV text.

    Args are passed through to
    :func:`insights.service_revenue.revenue_by_service`. An empty
    window exports as the header row alone. Lines end ``"\\n"``.
    """
    rows = revenue_by_service(salon, start, end, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=SERVICE_REVENUE_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "service_id": _int_or_empty(row.service_id),
            "service_name": row.service_name,
            "revenue": _money(row.revenue),
            "quantity": row.quantity,
            "line_count": row.line_count,
            "sale_count": row.sale_count,
            "duration_minutes": _int_or_empty(row.duration_minutes),
            "total_duration_minutes": _int_or_empty(
                row.total_duration_minutes),
            "revenue_per_hour": (
                "" if row.revenue_per_hour is None
                else _money(row.revenue_per_hour)
            ),
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
service_revenue_csv = export_service_revenue_csv
