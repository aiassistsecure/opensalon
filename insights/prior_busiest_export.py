"""Prior-period busiest-days comparison export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the comparison from
:mod:`insights.prior_busiest` verbatim — it never recomputes
a figure, a delta, or a percentage. Following
:mod:`insights.busiest_export`, it offers a plain,
JSON-serializable list of dicts (:func:`export_prior_busiest`)
and a CSV string (:func:`export_prior_busiest_csv`) built from
that same list, so the two formats can never disagree.

One row per weekday, in weekday order, keyed by weekday.
Columns carry both window bounds plus, for each figure
(``count``, ``appointment_value``, ``revenue``), its current
value, prior value, ``delta``, and ``percent_change``.
Money/percentages render to two places, never via a float;
counts as integers; ``None`` percent (zero prior) renders empty.
"""
import csv
import io
from decimal import Decimal

from insights.prior_busiest import prior_busiest

__all__ = [
    "PRIOR_BUSIEST_FIELDNAMES", "PRIOR_BUSIEST_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES", "export_prior_busiest",
    "export_prior_busiest_csv", "export_prior_busiest_comparison_csv",
    "prior_busiest_csv",
]

PRIOR_BUSIEST_FIELDNAMES = [
    "weekday", "weekday_name",
    "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date",
    "current_count", "prior_count", "count_delta",
    "count_percent_change",
    "current_appointment_value", "prior_appointment_value",
    "appointment_value_delta", "appointment_value_percent_change",
    "current_revenue", "prior_revenue", "revenue_delta",
    "revenue_percent_change",
]
PRIOR_BUSIEST_EXPORT_FIELDNAMES = PRIOR_BUSIEST_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_BUSIEST_FIELDNAMES

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _record(result, row):
    return {
        "weekday": row.weekday, "weekday_name": row.weekday_name,
        "current_start_date": result.start_date.isoformat(),
        "current_end_date": result.end_date.isoformat(),
        "prior_start_date": result.prior_start_date.isoformat(),
        "prior_end_date": result.prior_end_date.isoformat(),
        "current_count": int(row.count.current),
        "prior_count": int(row.count.prior),
        "count_delta": int(row.count.delta),
        "count_percent_change": _pct(row.count.percent_change),
        "current_appointment_value": _money(row.appointment_value.current),
        "prior_appointment_value": _money(row.appointment_value.prior),
        "appointment_value_delta": _money(row.appointment_value.delta),
        "appointment_value_percent_change": _pct(
            row.appointment_value.percent_change),
        "current_revenue": _money(row.revenue.current),
        "prior_revenue": _money(row.revenue.prior),
        "revenue_delta": _money(row.revenue.delta),
        "revenue_percent_change": _pct(row.revenue.percent_change),
    }


def export_prior_busiest(salon, start_date=None, end_date=None, **kwargs):
    """Return ``salon``'s prior busiest-days comparison as dicts.

    Args mirror :func:`insights.prior_busiest.prior_busiest`
    exactly; its values are rendered unchanged. Seven records,
    one per weekday in weekday order, never an empty list.
    """
    result = prior_busiest(salon, start_date, end_date, **kwargs)
    return [_record(result, row) for row in result.weekdays]


def export_prior_busiest_csv(salon, start_date=None, end_date=None,
                             **kwargs):
    """Return ``salon``'s prior busiest-days comparison as CSV.

    The header is :data:`PRIOR_BUSIEST_FIELDNAMES` and every
    data row comes from :func:`export_prior_busiest` with the
    same arguments, so the CSV and list exports always agree.
    Lines end with ``"\\n"``.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_BUSIEST_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_prior_busiest(salon, start_date, end_date,
                                       **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_prior_busiest_comparison_csv = export_prior_busiest_csv
prior_busiest_csv = export_prior_busiest_csv
