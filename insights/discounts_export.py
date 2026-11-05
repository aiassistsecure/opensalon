"""Discounts CSV export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the result of
:mod:`insights.discounts` verbatim — it never recomputes gross,
discounts, or the share. One row for the window, columns
``start_date``, ``end_date``, ``days``, ``gross_revenue``,
``discount_total``, ``discount_share_percent``. Money/percents
render to two places, never via a float; a ``None`` share
renders empty. A plain dict row
(:func:`export_discounts_row`) backs the CSV, so the two
formats can never disagree.
"""
import csv
import io
from decimal import Decimal

from insights.discounts import discounts_report

__all__ = [
    "DISCOUNTS_FIELDNAMES",
    "DISCOUNTS_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_discounts_csv",
    "export_discounts_row",
    "export_discount_report_csv",
    "discounts_csv",
]

DISCOUNTS_FIELDNAMES = [
    "start_date", "end_date", "days", "gross_revenue",
    "discount_total", "discount_share_percent",
]
DISCOUNTS_EXPORT_FIELDNAMES = DISCOUNTS_FIELDNAMES
EXPORT_FIELDNAMES = DISCOUNTS_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else _money(value)


def export_discounts_row(salon, start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s discounts report as a single dict row.

    Args mirror :func:`insights.discounts.discounts_report`
    exactly; its result's values are rendered unchanged.
    """
    result = discounts_report(salon, start_date, end_date, **kwargs)
    return {
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat(),
        "days": result.days,
        "gross_revenue": _money(result.gross),
        "discount_total": _money(result.discount_total),
        "discount_share_percent": _pct(result.discount_share_percent),
    }


def export_discounts_csv(salon, start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s discounts report as a CSV string.

    Built from :func:`export_discounts_row` with the same
    arguments, so the CSV and dict exports always agree.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=DISCOUNTS_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    writer.writerow(export_discounts_row(
        salon, start_date, end_date, **kwargs))
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_discount_report_csv = export_discounts_csv
discounts_csv = export_discounts_csv
