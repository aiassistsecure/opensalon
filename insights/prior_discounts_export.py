"""Prior-period discounts comparison CSV/JSON export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the comparison from
:mod:`insights.prior_discounts` verbatim — it never recomputes
a figure, a delta, or a percentage. One row per metric
(``discount_total``, ``gross``, ``discount_share_percent``).
Columns: ``metric``, current/prior window bounds, ``current``,
``prior``, ``delta``, ``percent_change``. Money/percentages
render to two places, never via a float; ``None`` renders empty.

A plain list of dict rows (:func:`export_prior_discounts`)
backs the CSV, so the two formats can never disagree.
"""
import csv
import io
from decimal import Decimal

from insights.prior_discounts import prior_discounts

__all__ = [
    "PRIOR_DISCOUNTS_FIELDNAMES",
    "PRIOR_DISCOUNTS_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_prior_discounts",
    "export_prior_discounts_csv",
    "export_prior_discounts_comparison_csv",
    "prior_discounts_csv",
]

PRIOR_DISCOUNTS_FIELDNAMES = [
    "metric",
    "current_start_date",
    "current_end_date",
    "prior_start_date",
    "prior_end_date",
    "current",
    "prior",
    "delta",
    "percent_change",
]
PRIOR_DISCOUNTS_EXPORT_FIELDNAMES = PRIOR_DISCOUNTS_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_DISCOUNTS_FIELDNAMES

_CENTS = Decimal("0.01")
_METRICS = ("discount_total", "gross", "discount_share_percent")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def export_prior_discounts(salon, start_date=None, end_date=None,
                           **kwargs):
    """Return ``salon``'s prior-period discounts comparison as dicts.

    Every row mirrors a CSV cell exactly: keys are
    :data:`PRIOR_DISCOUNTS_FIELDNAMES` in order, dates are ISO
    strings, and money/percentages are strings rendered to two
    places (``""`` where the CSV renders empty). Args mirror
    :func:`insights.prior_discounts.prior_discounts` exactly;
    its result's values are rendered unchanged.
    """
    result = prior_discounts(salon, start_date, end_date, **kwargs)
    rows = []
    for name in _METRICS:
        comp = getattr(result, name)
        if comp is None:
            # Share delta undefined: render the verbatim shares.
            current = result.current.discount_share_percent
            prior = result.prior.discount_share_percent
            row_current, row_prior, row_delta, row_pct = (
                _pct(current), _pct(prior), "", "")
        else:
            row_current, row_prior = _money(comp.current), _money(comp.prior)
            row_delta, row_pct = _money(comp.delta), _pct(comp.percent_change)
        rows.append({
            "metric": name,
            "current_start_date": result.current.start_date.isoformat(),
            "current_end_date": result.current.end_date.isoformat(),
            "prior_start_date": result.prior.start_date.isoformat(),
            "prior_end_date": result.prior.end_date.isoformat(),
            "current": row_current,
            "prior": row_prior,
            "delta": row_delta,
            "percent_change": row_pct,
        })
    return rows


def export_prior_discounts_csv(salon, start_date=None, end_date=None,
                               **kwargs):
    """Return ``salon``'s prior-period discounts comparison as CSV.

    Args mirror :func:`insights.prior_discounts.prior_discounts`
    exactly; its result's values are rendered unchanged. Built
    from :func:`export_prior_discounts` with the same arguments,
    so the CSV and dict exports always agree.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_DISCOUNTS_FIELDNAMES,
        lineterminator="\n"
    )
    writer.writeheader()
    for row in export_prior_discounts(salon, start_date, end_date,
                                      **kwargs):
        writer.writerow(row)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_prior_discounts_comparison_csv = export_prior_discounts_csv
prior_discounts_csv = export_prior_discounts_csv
