"""Prior-period revenue-split comparison CSV export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it can
fully export. This module exports the comparison from
:mod:`insights.prior_period` verbatim — it never recomputes a
split, a delta, or a percentage. One row per component
(``service``, ``retail``, ``series``, ``total``), in that order.

Columns: ``component``, the current and prior window bounds,
``current``, ``prior``, ``delta``, and ``percent_change``.
Money and percentages render to two decimal places, never via a
float; a ``None`` percent change (zero prior component — see
:mod:`insights.prior_period`) renders as an empty string.
"""
import csv
import io
from decimal import Decimal

from insights.prior_period import prior_period_revenue_split

__all__ = [
    "PRIOR_PERIOD_FIELDNAMES",
    "PRIOR_PERIOD_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_prior_period_csv",
    "export_prior_period_revenue_split_csv",
    "prior_period_csv",
]

PRIOR_PERIOD_FIELDNAMES = [
    "component",
    "current_start_date",
    "current_end_date",
    "prior_start_date",
    "prior_end_date",
    "current",
    "prior",
    "delta",
    "percent_change",
]
PRIOR_PERIOD_EXPORT_FIELDNAMES = PRIOR_PERIOD_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_PERIOD_FIELDNAMES

_CENTS = Decimal("0.01")
_COMPONENTS = ("service", "retail", "series", "total")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def export_prior_period_csv(salon, start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s prior-period comparison as a CSV string.

    Args mirror :func:`insights.prior_period.prior_period_revenue_split`
    exactly; its result's values are rendered unchanged.
    """
    result = prior_period_revenue_split(
        salon, start_date, end_date, **kwargs
    )
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_PERIOD_FIELDNAMES, lineterminator="\n"
    )
    writer.writeheader()
    for name in _COMPONENTS:
        comp = getattr(result, name)
        writer.writerow({
            "component": name,
            "current_start_date": result.current.start_date.isoformat(),
            "current_end_date": result.current.end_date.isoformat(),
            "prior_start_date": result.prior.start_date.isoformat(),
            "prior_end_date": result.prior.end_date.isoformat(),
            "current": _money(comp.current),
            "prior": _money(comp.prior),
            "delta": _money(comp.delta),
            "percent_change": _pct(comp.percent_change),
        })
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_prior_period_revenue_split_csv = export_prior_period_csv
prior_period_csv = export_prior_period_csv
