"""Prior-period daily revenue trend comparison export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the comparison from
:mod:`insights.prior_trend` verbatim — it never recomputes a
figure, a delta, or a percentage. Following
:mod:`insights.prior_busiest_export`, it offers a plain,
JSON-serializable list of dicts (:func:`export_prior_trend`)
and a CSV string (:func:`export_prior_trend_csv`) built from
that same list, so the two formats can never disagree.

One row per day, in window order, offset-aligned. Columns carry
both window bounds plus, for each figure (``service``,
``retail``, ``series``, ``total``, ``moving_average_7d``), its
current value, prior value, ``delta``, and ``percent_change``.
Money/percentages render to two places, never via a float;
``None`` percent (zero prior) renders empty.
"""
import csv
import io
from decimal import Decimal

from insights.prior_trend import prior_trend

__all__ = [
    "PRIOR_TREND_FIELDNAMES", "PRIOR_TREND_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_prior_trend", "export_prior_trend_csv",
    "export_prior_trend_comparison_csv", "prior_trend_csv",
]

_FIGURES = ("service", "retail", "series", "total", "moving_average_7d")

# Column order: per figure, current, prior, delta, percent_change.
PRIOR_TREND_FIELDNAMES = (
    ["offset", "current_date", "prior_date", "current_start_date",
     "current_end_date", "prior_start_date", "prior_end_date"]
    + [column for figure in _FIGURES for column in (
        f"current_{figure}", f"prior_{figure}", f"{figure}_delta",
        f"{figure}_percent_change")]
)
PRIOR_TREND_EXPORT_FIELDNAMES = PRIOR_TREND_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_TREND_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _record(result, row):
    record = {
        "offset": row.offset,
        "current_date": row.current.date.isoformat(),
        "prior_date": row.prior.date.isoformat(),
        "current_start_date": result.start_date.isoformat(),
        "current_end_date": result.end_date.isoformat(),
        "prior_start_date": result.prior_start_date.isoformat(),
        "prior_end_date": result.prior_end_date.isoformat(),
    }
    for figure in _FIGURES:
        comp = getattr(row, figure)
        record[f"current_{figure}"] = _money(comp.current)
        record[f"prior_{figure}"] = _money(comp.prior)
        record[f"{figure}_delta"] = _money(comp.delta)
        record[f"{figure}_percent_change"] = _pct(comp.percent_change)
    return record


def export_prior_trend(salon, start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s prior trend comparison as dicts.

    Args mirror :func:`insights.prior_trend.prior_trend` exactly;
    its values are rendered unchanged. One record per day of the
    window, in window order, never an empty list.
    """
    result = prior_trend(salon, start_date, end_date, **kwargs)
    return [_record(result, row) for row in result.per_day]


def export_prior_trend_csv(salon, start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s prior trend comparison as CSV.

    The header is :data:`PRIOR_TREND_FIELDNAMES` and every data
    row comes from :func:`export_prior_trend` with the same
    arguments, so the CSV and list exports always agree.
    Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_TREND_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_prior_trend(salon, start_date, end_date, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_prior_trend_comparison_csv = export_prior_trend_csv
prior_trend_csv = export_prior_trend_csv
