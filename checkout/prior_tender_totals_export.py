"""Read-only prior-period tender-totals CSV export.

Backend only, read-only. Exit Principle: renders
:mod:`checkout.prior_tender_totals` as dicts and as CSV built
from that same list, following prior_tender_mix_export's shape
(minus shares): salon_id, current/prior bounds, method,
current/prior, delta, percent_change (empty when ``None``),
window totals and count delta repeated per row. Lines ``"\n"``.
"""
import csv
import io
from decimal import Decimal

from .prior_tender_totals import prior_tender_totals

__all__ = ["EXPORT_FIELDNAMES", "export_prior_tender_totals",
           "export_prior_tender_totals_csv", "export_prior_tender_totals_rows",
           "prior_tender_totals_csv", "prior_tender_totals_export_row"]

EXPORT_FIELDNAMES = [
    "salon_id", "start", "end", "prior_start", "prior_end",
    "method", "current", "prior", "delta", "percent_change",
    "current_total", "prior_total", "current_count", "prior_count",
    "count_delta", "count_percent_change",
]

_CENTS = Decimal("0.01")


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else _money(value)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def prior_tender_totals_export_row(entry, result):
    return {
        "salon_id": result.salon_id,
        "start": _iso(result.start), "end": _iso(result.end),
        "prior_start": _iso(result.prior_start),
        "prior_end": _iso(result.prior_end),
        "method": entry.method,
        "current": _money(entry.current), "prior": _money(entry.prior),
        "delta": _money(entry.delta),
        "percent_change": _pct(entry.percent_change),
        "current_total": _money(result.current.total),
        "prior_total": _money(result.prior.total),
        "current_count": result.current.count,
        "prior_count": result.prior.count,
        "count_delta": result.count.delta,
        "count_percent_change": _pct(result.count.percent_change),
    }


def export_prior_tender_totals(start=None, end=None, salon=None, **kwargs):
    """Return the prior tender totals as dict rows."""
    result = prior_tender_totals(start, end, salon=salon, **kwargs)
    return [prior_tender_totals_export_row(e, result) for e in result.entries]


def export_prior_tender_totals_csv(start=None, end=None, salon=None, **kwargs):
    """Return :func:`export_prior_tender_totals` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_prior_tender_totals(start, end, salon=salon, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_prior_tender_totals_rows = export_prior_tender_totals
prior_tender_totals_csv = export_prior_tender_totals_csv
