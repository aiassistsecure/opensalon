"""Week / month revenue rollup CSV export service.

Backend only — no views, templates, or UI. Read-only. Founding
rule (Exit Principle): anything a salon can enter, it can fully
export. Exports :mod:`insights.rollup` verbatim — never recomputes
a bucket; ordering (oldest first) and values are the service's, so
the CSV reconciles with the daily trend. Money renders to two
decimal places, never via a float.
"""
import csv
import io
from decimal import Decimal

from insights.rollup import revenue_rollup

__all__ = [
    "ROLLUP_FIELDNAMES", "ROLLUP_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_rollup_csv",
    "export_weekly_rollup_csv", "export_monthly_rollup_csv",
    "export_revenue_rollup_csv", "rollup_csv",
]

ROLLUP_FIELDNAMES = [
    "granularity", "label", "period_start", "period_end",
    "day_count", "service", "retail", "series", "total",
]
ROLLUP_EXPORT_FIELDNAMES = ROLLUP_FIELDNAMES
EXPORT_FIELDNAMES = ROLLUP_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def export_rollup_csv(salon, granularity="week", days=None,
                      end_date=None, **kwargs):
    """Return the rollup as CSV; args mirror the rollup service.

    ``today`` is accepted as the ``end_date`` alias; an empty
    window exports as the header row alone.
    """
    if "today" in kwargs:
        if end_date is not None:
            raise TypeError("Pass only one of end_date / today.")
        end_date = kwargs.pop("today")
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    rows = revenue_rollup(
        salon, granularity=granularity, days=days, end_date=end_date)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ROLLUP_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "granularity": row.granularity,
            "label": row.label,
            "period_start": row.start_date.isoformat(),
            "period_end": row.end_date.isoformat(),
            "day_count": row.day_count,
            "service": _money(row.service),
            "retail": _money(row.retail),
            "series": _money(row.series),
            "total": _money(row.total),
        })
    return buffer.getvalue()


def export_weekly_rollup_csv(salon, days=None, end_date=None, **kwargs):
    """Return the weekly rollup CSV (see :func:`export_rollup_csv`)."""
    return export_rollup_csv(
        salon, granularity="week", days=days, end_date=end_date, **kwargs)


def export_monthly_rollup_csv(salon, days=None, end_date=None, **kwargs):
    """Return the monthly rollup CSV (see :func:`export_rollup_csv`)."""
    return export_rollup_csv(
        salon, granularity="month", days=days, end_date=end_date, **kwargs)


export_revenue_rollup_csv = export_rollup_csv
rollup_csv = export_rollup_csv
