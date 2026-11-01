"""Daily revenue trend CSV export service.

Backend only — no views, templates, or UI. Read-only: this
service never creates, edits, or deletes a sale.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports a salon's daily revenue trend
as a CSV string built ON TOP of :mod:`insights.trend` — the
definition of daily revenue (completed sales only, salon scoping,
sale day judged in the salon's timezone, service / retail / series split,
and the trailing 7-day moving average) is that service's alone
and is reused verbatim via
:func:`insights.trend.daily_revenue_trend`; this module never
reimplements that math, re-queries sales, or re-orders rows.
Ordering is exactly the service's ordering: oldest day first.

Columns are only fields the service's rows actually carry:

- ``date``: the row's calendar date (ISO date).
- ``service``: the row's service revenue.
- ``retail``: the row's retail (product) revenue.
- ``series``: the row's series revenue.
- ``total``: the row's total revenue.
- ``moving_average_7d``: the row's trailing 7-day moving
  average of ``total``.

Money is rendered as a string to two decimal places, never
passed through a float.
"""
import csv
import io
from decimal import Decimal

from insights.trend import daily_revenue_trend

__all__ = [
    "TREND_FIELDNAMES",
    "TREND_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_trend_csv",
    "export_revenue_trend_csv",
    "trend_csv",
    "revenue_trend_csv",
]

#: Column order of the CSV export.
TREND_FIELDNAMES = [
    "date",
    "service",
    "retail",
    "series",
    "total",
    "moving_average_7d",
]

TREND_EXPORT_FIELDNAMES = TREND_FIELDNAMES
EXPORT_FIELDNAMES = TREND_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_trend_csv(salon, days=14, end_date=None, **kwargs):
    """Return ``salon``'s daily revenue trend as a CSV string.

    Args:
        salon: ``saloncore.Salon`` instance to scope to, passed
            through to
            :func:`insights.trend.daily_revenue_trend`.
        days: number of calendar days in the window, as accepted
            by that service.
        end_date: inclusive window end, as accepted by that
            service.
        **kwargs: forwarded to that service (including its
            ``today`` keyword alias for ``end_date``).

    Returns:
        A CSV string whose header row is
        :data:`TREND_FIELDNAMES` and whose data rows follow
        the trend service's ordering exactly (oldest first),
        with values matching that service's rows. A window
        with no days (``days <= 0``) exports as the header
        row alone; days with no sales export as zero rows,
        exactly as the service returns them. Lines end with
        ``"\\n"``.
    """
    rows = daily_revenue_trend(salon, days, end_date=end_date, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=TREND_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "date": row.date.isoformat(),
            "service": _money(row.service),
            "retail": _money(row.retail),
            "series": _money(row.series),
            "total": _money(row.total),
            "moving_average_7d": _money(row.moving_average_7d),
        })
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_revenue_trend_csv = export_trend_csv
trend_csv = export_trend_csv
revenue_trend_csv = export_trend_csv
