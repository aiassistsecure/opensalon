"""Read-only prior (same-weekday) daily-sales CSV export.

Backend only, read-only. Exit Principle: renders
:mod:`checkout.prior_daily_sales` as a list of dicts and as CSV
built from that same list, so the formats can never disagree;
every value comes verbatim from the service. One row per
figure, in order: ``sales_count``, ``gross_total``,
``discount_total``, ``net_total``, ``service_total``,
``retail_total``, ``series_total``, ``item_count``. Money renders as Decimal
strings to two places, counts as integers, and a ``None``
percent change (zero prior) renders empty. Lines end ``"\\n"``.
"""
import csv
import io
from decimal import Decimal

from .prior_daily_sales import FIGURES, prior_daily_sales

__all__ = ["EXPORT_FIELDNAMES", "export_prior_daily_sales",
           "export_prior_daily_sales_csv", "export_prior_daily_sales_rows",
           "prior_daily_sales_csv", "prior_daily_sales_export_row"]

EXPORT_FIELDNAMES = ["salon_id", "date", "prior_date", "figure",
                     "current", "prior", "delta", "percent_change"]
_CENTS = Decimal("0.01")
_COUNTS = ("sales_count", "item_count")


def _money(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _value(figure, value):
    if value is None:
        return ""
    return str(int(value)) if figure in _COUNTS else _money(value)


def prior_daily_sales_export_row(figure, delta, result):
    return {"salon_id": result.salon_id,
            "date": result.date.isoformat(),
            "prior_date": result.prior_date.isoformat(),
            "figure": figure,
            "current": _value(figure, delta.current),
            "prior": _value(figure, delta.prior),
            "delta": _value(figure, delta.delta),
            "percent_change": _money(delta.percent_change)}


def export_prior_daily_sales(salon, day=None, **kwargs):
    """Return the prior daily-sales comparison as dict rows."""
    result = prior_daily_sales(salon, day, **kwargs)
    return [prior_daily_sales_export_row(name, getattr(result, name), result)
            for name in FIGURES]


def export_prior_daily_sales_csv(salon, day=None, **kwargs):
    """Return :func:`export_prior_daily_sales` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_FIELDNAMES,
                            lineterminator="\n")
    writer.writeheader()
    for record in export_prior_daily_sales(salon, day, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring sibling services.
export_prior_daily_sales_rows = export_prior_daily_sales
prior_daily_sales_csv = export_prior_daily_sales_csv
