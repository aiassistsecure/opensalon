"""Read-only prior-period tender-mix CSV export for checkout.

Backend only, read-only. Exit Principle: renders
:mod:`checkout.prior_tender_mix` as a list of dicts and as CSV
built from that same list, so the formats can never disagree;
every value comes verbatim from the service. Columns:
``salon_id``, current/prior window bounds (ISO-8601),
``method``, ``current`` / ``prior``, ``delta``,
``percent_change``, both share percents (empty when ``None``),
and window totals/counts repeated per row, plus the salon-level
payment-count delta (``count_delta`` / ``count_percent_change``,
from the service's ``count`` MetricDelta; empty percent when
``None``) repeated per row. Lines end ``"\\n"``.
"""
import csv
import io
from decimal import Decimal

from .prior_tender_mix import prior_tender_mix

__all__ = [
    "EXPORT_FIELDNAMES", "export_prior_tender_mix",
    "export_prior_tender_mix_csv", "export_prior_tender_mix_rows",
    "prior_tender_mix_csv", "prior_tender_mix_export_row"]

EXPORT_FIELDNAMES = [
    "salon_id", "start", "end", "prior_start", "prior_end",
    "method", "current", "prior", "delta", "percent_change",
    "current_share_percent", "prior_share_percent",
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


def prior_tender_mix_export_row(entry, result):
    return {
        "salon_id": result.salon_id,
        "start": _iso(result.start), "end": _iso(result.end),
        "prior_start": _iso(result.prior_start),
        "prior_end": _iso(result.prior_end),
        "method": entry.method,
        "current": _money(entry.current), "prior": _money(entry.prior),
        "delta": _money(entry.delta),
        "percent_change": _pct(entry.percent_change),
        "current_share_percent": _pct(entry.current_share_percent),
        "prior_share_percent": _pct(entry.prior_share_percent),
        "current_total": _money(result.current.total),
        "prior_total": _money(result.prior.total),
        "current_count": result.current.count,
        "prior_count": result.prior.count,
        "count_delta": result.count.delta,
        "count_percent_change": _pct(result.count.percent_change),
    }


def export_prior_tender_mix(salon, start=None, end=None, **kwargs):
    """Return the prior tender mix for ``salon`` as dict rows."""
    result = prior_tender_mix(salon, start, end, **kwargs)
    return [prior_tender_mix_export_row(e, result) for e in result.entries]


def export_prior_tender_mix_csv(salon, start=None, end=None, **kwargs):
    """Return :func:`export_prior_tender_mix` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_prior_tender_mix(salon, start, end, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_prior_tender_mix_rows = export_prior_tender_mix
prior_tender_mix_csv = export_prior_tender_mix_csv
