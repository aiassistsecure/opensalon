"""Service-category mix CSV/JSON export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. Built ON TOP of :mod:`insights.category_mix` — its
definition (completed service items only, window, grouping,
ranking, shares) is reused verbatim; this module never
reimplements it or re-orders rows. ``category_id`` is empty for
the uncategorized row, a share empty when ``None``. Money and
percents render to two decimal places, never through a float.

A plain list of dict rows (:func:`export_category_mix`) backs
the CSV, so the two formats can never disagree.
"""
import csv
import io
from decimal import Decimal

from insights.category_mix import category_mix

__all__ = ["CATEGORY_MIX_FIELDNAMES", "CATEGORY_MIX_EXPORT_FIELDNAMES",
           "EXPORT_FIELDNAMES", "export_category_mix",
           "export_category_mix_csv", "category_mix_csv"]

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


def export_category_mix(salon, start, end, **kwargs):
    """Return ``salon``'s service-category mix as a list of dicts.

    Every row mirrors a CSV cell exactly: keys are
    :data:`CATEGORY_MIX_FIELDNAMES` in order, ``category_id`` is
    the category's id or ``""`` for the uncategorized row, counts
    are ints, and money / percents are strings to two decimal
    places (a share is ``""`` when ``None``). Rows come verbatim
    from :func:`insights.category_mix.category_mix` for the same
    salon and window, in that service's order. An empty window
    exports as an empty list. Records nothing.
    """
    rows = category_mix(salon, start, end, **kwargs)
    return [{
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
    } for row in rows]


def export_category_mix_csv(salon, start, end, **kwargs):
    """Return ``salon``'s service-category mix report as CSV text.

    Args are passed through to
    :func:`insights.category_mix.category_mix`. Built from
    :func:`export_category_mix` with the same arguments, so the
    CSV and dict exports always agree. An empty window exports
    as the header row alone. Lines end ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CATEGORY_MIX_FIELDNAMES,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in export_category_mix(salon, start, end, **kwargs):
        writer.writerow(row)
    return buffer.getvalue()


#: Alias, mirroring the naming convenience in sibling services.
category_mix_csv = export_category_mix_csv
