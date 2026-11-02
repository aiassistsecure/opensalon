"""Prior-period retention/returning comparison CSV export.

Backend only — no views, templates, or UI. Read-only. Exit
Principle: renders :mod:`insights.prior_retention_returning`
verbatim, never recomputes. One row per metric. Columns:
``metric``, window bounds, ``current``, ``prior``, ``delta``,
``percent_change``. Counts are integers, money/percent two
places, retention rates four, ``None`` percent empty.
"""
import csv
import io
from decimal import Decimal

from .prior_retention_returning import (
    prior_period_retention, prior_period_returning_revenue)

__all__ = [
    "PRIOR_RETENTION_FIELDNAMES", "PRIOR_RETURNING_FIELDNAMES",
    "PRIOR_RETENTION_RETURNING_FIELDNAMES",
    "export_prior_retention_csv", "export_prior_returning_csv",
    "export_prior_retention_returning_csv",
]

PRIOR_RETENTION_FIELDNAMES = [
    "metric", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "current", "prior",
    "delta", "percent_change",
]
PRIOR_RETURNING_FIELDNAMES = list(PRIOR_RETENTION_FIELDNAMES)
PRIOR_RETENTION_RETURNING_FIELDNAMES = PRIOR_RETENTION_FIELDNAMES

_CENTS = Decimal("0.01")
_RATE = Decimal("0.0001")
_RETENTION_METRICS = (
    "active_clients", "repeat_clients", "total_visits",
    "repeat_rate", "average_visits_per_active_client",
)
_RETENTION_COUNTS = ("active_clients", "repeat_clients", "total_visits")
_RETURNING_METRICS = (
    "returning_revenue", "new_revenue", "unattributed_revenue",
    "total", "returning_sale_count", "new_sale_count",
    "unattributed_sale_count", "total_sale_count",
)
_RETURNING_COUNTS = (
    "returning_sale_count", "new_sale_count",
    "unattributed_sale_count", "total_sale_count",
)


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _count(value):
    return str(int(Decimal(value)))


def _rate(value):
    return str(Decimal(value).quantize(_RATE))


def _write(rows, fieldnames):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames,
                            lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def _bounds(result):
    return {
        "current_start_date": result.start_date.isoformat(),
        "current_end_date": result.end_date.isoformat(),
        "prior_start_date": result.prior_start_date.isoformat(),
        "prior_end_date": result.prior_end_date.isoformat(),
    }


def _rows(result, metrics, fmt):
    return [{
        "metric": name, **_bounds(result),
        "current": fmt(name, getattr(result, name).current),
        "prior": fmt(name, getattr(result, name).prior),
        "delta": fmt(name, getattr(result, name).delta),
        "percent_change": _pct(getattr(result, name).percent_change),
    } for name in metrics]


def export_prior_retention_csv(salon, start_date=None, end_date=None,
                               **kwargs):
    """Return the retention prior-period comparison as CSV."""
    result = prior_period_retention(salon, start_date, end_date,
                                    **kwargs)
    fmt = lambda n, v: _count(v) if n in _RETENTION_COUNTS else _rate(v)  # noqa: E731
    return _write(_rows(result, _RETENTION_METRICS, fmt),
                  PRIOR_RETENTION_FIELDNAMES)


def export_prior_returning_csv(salon, start_date=None, end_date=None,
                               **kwargs):
    """Return the returning-revenue prior comparison as CSV."""
    result = prior_period_returning_revenue(
        salon, start_date, end_date, **kwargs)
    fmt = lambda n, v: _count(v) if n in _RETURNING_COUNTS else _money(v)  # noqa: E731
    return _write(_rows(result, _RETURNING_METRICS, fmt),
                  PRIOR_RETURNING_FIELDNAMES)


#: Combined-name alias: retention is the default comparison.
export_prior_retention_returning_csv = export_prior_retention_csv
