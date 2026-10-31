"""New-vs-returning revenue CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale, sale item,
appointment, or client.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's new-vs-returning
revenue report as a CSV string built ON TOP of
:mod:`insights.returning` — the definition of the split
(completed sales only, salon scoping, effective date judged in
the salon's timezone, per-client first-ever classification,
unattributed bucket for sales with no usable client link) is
that service's alone and is reused verbatim via
:func:`insights.returning.new_vs_returning_revenue`; this module
never reimplements that classification, re-queries sales or
appointments, or invents fields.

The service returns a single
:class:`insights.returning.ReturningRevenue` for the window, so
the export is exactly one data row.

Columns are only fields the service's result actually carries:

- ``start_date``: the result's inclusive window start (ISO date).
- ``end_date``: the result's inclusive window end (ISO date).
- ``returning_revenue``: the result's returning-client revenue.
- ``new_revenue``: the result's new-client revenue.
- ``unattributed_revenue``: the result's unattributed revenue.
- ``total``: the result's total revenue.
- ``returning_sale_count``: the result's returning sale count.
- ``new_sale_count``: the result's new sale count.
- ``unattributed_sale_count``: the result's unattributed
  sale count.

The result's alias properties (``returning``, ``new``,
``unattributed``, ``total_revenue``, ``total_sale_count``) are
not exported as separate columns — they repeat fields above
(``total_sale_count`` is the sum of the three exported counts).

Money is rendered as a string to two decimal places, never
passed through a float.
"""
import csv
import io
from decimal import Decimal

from insights.returning import new_vs_returning_revenue

__all__ = [
    "RETURNING_FIELDNAMES",
    "RETURNING_REVENUE_FIELDNAMES",
    "RETURNING_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_returning_revenue_csv",
    "export_returning_csv",
    "returning_revenue_csv",
    "returning_csv",
]

#: Column order of the CSV export.
RETURNING_FIELDNAMES = [
    "start_date",
    "end_date",
    "returning_revenue",
    "new_revenue",
    "unattributed_revenue",
    "total",
    "returning_sale_count",
    "new_sale_count",
    "unattributed_sale_count",
]

RETURNING_REVENUE_FIELDNAMES = RETURNING_FIELDNAMES
RETURNING_EXPORT_FIELDNAMES = RETURNING_FIELDNAMES
EXPORT_FIELDNAMES = RETURNING_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_returning_revenue_csv(salon, start, end, **kwargs):
    """Return ``salon``'s new-vs-returning revenue as a CSV string.

    Args:
        salon: ``saloncore.Salon`` instance to scope to, passed
            through to
            :func:`insights.returning.new_vs_returning_revenue`.
        start: inclusive window start, as accepted by that service.
        end: inclusive window end, as accepted by that service.
        **kwargs: forwarded to that service.

    Returns:
        A CSV string whose header row is
        :data:`RETURNING_FIELDNAMES` and whose single data row
        matches the returning-revenue service's result exactly.
        A window with no qualifying sales — or a reversed
        window — exports as that single zero row, exactly as
        the service returns it. Lines end with ``"\\n"``.
        Records nothing.
    """
    result = new_vs_returning_revenue(salon, start, end, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=RETURNING_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    writer.writerow({
        "start_date": result.start_date.isoformat(),
        "end_date": result.end_date.isoformat(),
        "returning_revenue": _money(result.returning_revenue),
        "new_revenue": _money(result.new_revenue),
        "unattributed_revenue": _money(result.unattributed_revenue),
        "total": _money(result.total),
        "returning_sale_count": result.returning_sale_count,
        "new_sale_count": result.new_sale_count,
        "unattributed_sale_count": result.unattributed_sale_count,
    })
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_returning_csv = export_returning_revenue_csv
returning_revenue_csv = export_returning_revenue_csv
returning_csv = export_returning_revenue_csv
