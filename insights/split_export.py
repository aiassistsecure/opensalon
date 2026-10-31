"""Last-7-days revenue split CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's last-7-days revenue
split as a CSV string built ON TOP of :mod:`insights.services` —
the definition of the split (completed sales only, salon scoping,
sale day judged in the salon's timezone, window of the 7 calendar
days ending on ``today``) is that service's alone and is reused
verbatim via
:func:`insights.services.last_7_days_revenue_split`; this module
never reimplements that math or re-queries sales.

The service returns a single
:class:`insights.services.RevenueSplit`, so the export is at most
one data row. There is no series column: ``SaleItem.Kind`` defines
only ``SERVICE`` and ``PRODUCT``, and the service deliberately
carries no series field — inventing one here would report a
permanently-zero category as if it were measured.

Columns are only fields the service's result actually carries:

- ``start_date``: the result's inclusive window start (ISO date).
- ``end_date``: the result's inclusive window end (ISO date).
- ``days``: the result's window length in days (7).
- ``service``: the result's service revenue.
- ``retail``: the result's retail (product) revenue.
- ``total``: the result's total revenue.

Money is rendered as a string to two decimal places, never
passed through a float.
"""
import csv
import io
from decimal import Decimal

from insights.services import last_7_days_revenue_split

__all__ = [
    "SPLIT_FIELDNAMES",
    "SPLIT_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_split_csv",
    "export_revenue_split_csv",
    "split_csv",
    "revenue_split_csv",
]

#: Column order of the CSV export.
SPLIT_FIELDNAMES = [
    "start_date",
    "end_date",
    "days",
    "service",
    "retail",
    "total",
]

SPLIT_EXPORT_FIELDNAMES = SPLIT_FIELDNAMES
EXPORT_FIELDNAMES = SPLIT_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_split_csv(salon, *, today=None, **kwargs):
    """Return ``salon``'s last-7-days revenue split as a CSV string.

    Args:
        salon: ``saloncore.Salon`` instance to scope to, passed
            through to
            :func:`insights.services.last_7_days_revenue_split`.
        today: inclusive window end, as accepted by that service.
        **kwargs: forwarded to that service.

    Returns:
        A CSV string whose header row is :data:`SPLIT_FIELDNAMES`
        and whose single data row matches the revenue-split
        service's result exactly. A salon with no qualifying
        sales (the service's zeroed split) exports as the header
        row alone. Lines end with ``"\\n"``.
    """
    result = last_7_days_revenue_split(salon, today=today, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=SPLIT_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    if result.total != Decimal("0.00"):
        writer.writerow({
            "start_date": result.start_date.isoformat(),
            "end_date": result.end_date.isoformat(),
            "days": result.days,
            "service": _money(result.service),
            "retail": _money(result.retail),
            "total": _money(result.total),
        })
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_revenue_split_csv = export_split_csv
split_csv = export_split_csv
revenue_split_csv = export_split_csv
