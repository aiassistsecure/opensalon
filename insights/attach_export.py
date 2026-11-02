"""Retail attach rate CSV export service.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Exports :mod:`insights.attach_rate` verbatim — never
recomputes a figure. Money renders to two decimal places, the
rate to four, and the percent to two, never via a float. An
empty / zero window still exports as one summary row of zeroes
(plus the header), so the file shape is stable.
"""
import csv
import io
from decimal import Decimal

from insights.attach_rate import retail_attach_rate

__all__ = [
    "ATTACH_RATE_FIELDNAMES", "ATTACH_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_attach_rate_csv",
    "export_retail_attach_rate_csv", "attach_rate_csv",
]

ATTACH_RATE_FIELDNAMES = [
    "start_date", "end_date", "days", "service_sales",
    "attached_sales", "unattached_service_sales",
    "product_only_sales", "total_completed_sales",
    "attach_rate", "attach_rate_percent", "service_revenue",
    "retail_revenue", "total_retail_revenue",
    "retail_revenue_per_service_sale",
    "retail_revenue_per_attached_sale", "retail_quantity",
]
ATTACH_EXPORT_FIELDNAMES = ATTACH_RATE_FIELDNAMES
EXPORT_FIELDNAMES = ATTACH_RATE_FIELDNAMES

_CENTS = Decimal("0.01")
_RATE = Decimal("0.0001")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_attach_rate_csv(salon, days=28, end_date=None, **kwargs):
    """Return the attach rate as a one-row CSV summary.

    Args mirror :func:`insights.attach_rate.retail_attach_rate`;
    ``today`` is accepted as the ``end_date`` alias.
    """
    if "today" in kwargs:
        if end_date is not None:
            raise TypeError("Pass only one of end_date / today.")
        end_date = kwargs.pop("today")
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    row = retail_attach_rate(salon, days=days, end_date=end_date)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ATTACH_RATE_FIELDNAMES,
        lineterminator="\n")
    writer.writeheader()
    writer.writerow({
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "days": row.days,
        "service_sales": row.service_sales,
        "attached_sales": row.attached_sales,
        "unattached_service_sales": row.unattached_service_sales,
        "product_only_sales": row.product_only_sales,
        "total_completed_sales": row.total_completed_sales,
        "attach_rate": str(row.attach_rate.quantize(_RATE)),
        "attach_rate_percent": _money(row.attach_rate_percent),
        "service_revenue": _money(row.service_revenue),
        "retail_revenue": _money(row.retail_revenue),
        "total_retail_revenue": _money(row.total_retail_revenue),
        "retail_revenue_per_service_sale":
            _money(row.retail_revenue_per_service_sale),
        "retail_revenue_per_attached_sale":
            _money(row.retail_revenue_per_attached_sale),
        "retail_quantity": row.retail_quantity,
    })
    return buffer.getvalue()


export_retail_attach_rate_csv = export_attach_rate_csv
attach_rate_csv = export_attach_rate_csv
