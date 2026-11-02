"""Read-only prior-period cashup-history CSV export for checkout.

Backend only, read-only. Exit Principle: renders
:mod:`checkout.prior_cashup_history` as a list of dicts and as
CSV built from that same list, so the formats can never
disagree; every value comes verbatim from the service. One row
per figure, in order: ``cashup_count``, ``total_taken``,
``expected_total``, ``variance``, then one ``by_tender`` row per
tender in the union of both windows. Money renders as Decimal
strings to two places, counts as integers, and a ``None`` figure
(unknown expected/variance, or a percent change on a zero
prior) renders empty. Lines end ``"\\n"``.
"""
import csv
import io
from decimal import Decimal

from .prior_cashup_history import prior_cashup_history

__all__ = [
    "EXPORT_FIELDNAMES", "export_prior_cashup_history",
    "export_prior_cashup_history_csv", "export_prior_cashup_history_rows",
    "prior_cashup_history_csv", "prior_cashup_history_export_row",
]

EXPORT_FIELDNAMES = [
    "salon_id", "start", "end", "prior_start", "prior_end",
    "figure", "tender", "current", "prior", "delta", "percent_change",
]

_CENTS = Decimal("0.01")
_FIGURES = ("cashup_count", "total_taken", "expected_total", "variance")
_COUNTS = ("cashup_count",)


def _money(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _value(figure, value):
    if value is None:
        return ""
    return str(int(value)) if figure in _COUNTS else _money(value)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def prior_cashup_history_export_row(figure, tender, delta, result):
    return {
        "salon_id": result.salon_id,
        "start": _iso(result.start), "end": _iso(result.end),
        "prior_start": _iso(result.prior_start),
        "prior_end": _iso(result.prior_end),
        "figure": figure, "tender": tender,
        "current": _value(figure, delta.current),
        "prior": _value(figure, delta.prior),
        "delta": _value(figure, delta.delta),
        "percent_change": _money(delta.percent_change),
    }


def export_prior_cashup_history(salon, start=None, end=None, **kwargs):
    """Return the prior cashup-history comparison as dict rows."""
    result = prior_cashup_history(salon, start, end, **kwargs)
    rows = [prior_cashup_history_export_row(
        name, "", getattr(result, name), result) for name in _FIGURES]
    rows += [prior_cashup_history_export_row(
        "by_tender", entry.method, entry.metric, result)
        for entry in result.entries]
    return rows


def export_prior_cashup_history_csv(salon, start=None, end=None, **kwargs):
    """Return :func:`export_prior_cashup_history` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_prior_cashup_history(salon, start, end, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_prior_cashup_history_rows = export_prior_cashup_history
prior_cashup_history_csv = export_prior_cashup_history_csv
