"""Read-only prior-period cashup-detail CSV export for checkout.

Backend only, read-only. Exit Principle: renders
:mod:`checkout.prior_cashup_detail` as a list of dicts and as CSV
built from that same list, so the formats can never disagree; every
value comes verbatim from the service. One row per figure: first the
totals (``tender`` empty) for ``gross``, ``refunds``, ``voids``,
``net``, ``payment_count``, ``refund_count``, ``void_count``, then
the same figures per tender. Money = Decimal strings to two places,
counts = integers, ``None`` percent change (zero prior) = empty.
Lines end ``"\\n"``.
"""
import csv
import io
from decimal import Decimal

from .prior_cashup_detail import ALL_FIGURES, COUNT_FIGURES, prior_cashup_detail

__all__ = ["EXPORT_FIELDNAMES", "export_prior_cashup_detail",
           "export_prior_cashup_detail_csv", "export_prior_cashup_detail_rows",
           "prior_cashup_detail_csv", "prior_cashup_detail_export_row"]
EXPORT_FIELDNAMES = [
    "salon_id", "start", "end", "prior_start", "prior_end",
    "figure", "tender", "current", "prior", "delta", "percent_change"]
_CENTS = Decimal("0.01")


def _money(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _value(figure, value):
    if value is None:
        return ""
    return str(int(value)) if figure in COUNT_FIGURES else _money(value)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def prior_cashup_detail_export_row(figure, tender, delta, result):
    return {
        "salon_id": result.salon_id,
        "start": _iso(result.start), "end": _iso(result.end),
        "prior_start": _iso(result.prior_start),
        "prior_end": _iso(result.prior_end),
        "figure": figure, "tender": tender,
        "current": _value(figure, delta.current),
        "prior": _value(figure, delta.prior),
        "delta": _value(figure, delta.delta),
        "percent_change": _money(delta.percent_change)}


def export_prior_cashup_detail(salon, start=None, end=None, **kwargs):
    """Return the prior cashup-detail comparison as dict rows."""
    result = prior_cashup_detail(salon, start, end, **kwargs)
    rows = [prior_cashup_detail_export_row(
        name, "", getattr(result, name), result) for name in ALL_FIGURES]
    for entry in result.entries:
        rows += [prior_cashup_detail_export_row(
            name, entry.tender, getattr(entry, name), result)
            for name in ALL_FIGURES]
    return rows


def export_prior_cashup_detail_csv(salon, start=None, end=None, **kwargs):
    """Return :func:`export_prior_cashup_detail` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_prior_cashup_detail(salon, start, end, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


export_prior_cashup_detail_rows = export_prior_cashup_detail
prior_cashup_detail_csv = export_prior_cashup_detail_csv
