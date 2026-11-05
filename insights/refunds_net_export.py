"""Refunds / net revenue CSV export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the result of
:mod:`insights.refunds_net` verbatim — it never recomputes
gross, refunds, or net. One row for the window.

Columns: ``start_date``, ``end_date``, ``days``,
``gross_revenue``, ``refund_total``, ``net_revenue``, and
``refund_count``. Money renders to two decimal places, never
via a float. A plain dict row
(:func:`export_refunds_net_row`) backs the CSV, so the two
formats can never disagree.
"""
import csv
import io
from decimal import Decimal

from insights.refunds_net import refunds_net_revenue

__all__ = [
    "REFUNDS_NET_FIELDNAMES",
    "REFUNDS_NET_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_refunds_net_csv",
    "export_refunds_net_row",
    "export_net_revenue_csv",
    "refunds_net_csv",
]

REFUNDS_NET_FIELDNAMES = [
    "start_date",
    "end_date",
    "days",
    "gross_revenue",
    "refund_total",
    "net_revenue",
    "refund_count",
]
REFUNDS_NET_EXPORT_FIELDNAMES = REFUNDS_NET_FIELDNAMES
EXPORT_FIELDNAMES = REFUNDS_NET_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_refunds_net_row(salon, start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s refunds/net revenue as a single dict row.

    Args mirror :func:`insights.refunds_net.refunds_net_revenue`
    exactly; its result's values are rendered unchanged.
    """
    result = refunds_net_revenue(salon, start_date, end_date, **kwargs)
    return {
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat(),
        "days": result.days,
        "gross_revenue": _money(result.gross),
        "refund_total": _money(result.refunds),
        "net_revenue": _money(result.net),
        "refund_count": result.refund_count,
    }


def export_refunds_net_csv(salon, start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s refunds/net revenue as a CSV string.

    Built from :func:`export_refunds_net_row` with the same
    arguments, so the CSV and dict exports always agree.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=REFUNDS_NET_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    writer.writerow(export_refunds_net_row(
        salon, start_date, end_date, **kwargs))
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_net_revenue_csv = export_refunds_net_csv
refunds_net_csv = export_refunds_net_csv
