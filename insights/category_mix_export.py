"""Service-category mix CSV export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. Built ON TOP of :mod:`insights.category_mix` — its
definition (completed service items only, window, grouping,
ranking, shares) is reused verbatim; this module never
reimplements it or re-orders rows. ``category_id`` is empty for
the uncategorized row, a share empty when ``None``. Money and
percents render to two decimal places, never through a float.
"""
import csv
import io
from decimal import Decimal

from insights.category_mix import category_mix

__all__ = ["CATEGORY_MIX_FIELDNAMES", "CATEGORY_MIX_EXPORT_FIELDNAMES",
           "EXPORT_FIELDNAMES", "export_category_mix_csv", "category_mix_csv"]

CATEGORY_MIX_FIELDNAMES = [
    "category_id", "category_name", "revenue", "quantity", "line_count",
    "sale_count", "service_count", "revenue_share_percent",
    "quantity_share_percent",
]

CATEGORY_MIX_EXPORT_FIELDNAMES = CATEGORY_MIX_FIELDNAMES
EXPORT_FIELDNAMES = CATEGORY_MIX_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else _money(value)


def export_category_mix_csv(salon, start, end, **kwargs):
    """Return ``salon``'s service-category mix report as CSV text.

    Args are passed through to
    :func:`insights.category_mix.category_mix`. An empty window
    exports as the header row alone. Lines end ``"\\n"``.
    """
    rows = category_mix(salon, start, end, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CATEGORY_MIX_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "category_id": (
                "" if row.category_id is None else row.category_id),
            "category_name": row.category_name,
            "revenue": _money(row.revenue),
            "quantity": row.quantity,
            "line_count": row.line_count,
            "sale_count": row.sale_count,
            "service_count": row.service_count,
            "revenue_share_percent": _pct(row.revenue_share_percent),
            "quantity_share_percent": _pct(row.quantity_share_percent),
        })
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
category_mix_csv = export_category_mix_csv
