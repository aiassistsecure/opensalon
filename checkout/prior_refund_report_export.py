"""Read-only prior-period refund-report CSV export for checkout.

Backend only, read-only. Exit Principle: renders
:mod:`checkout.prior_refund_report` as dicts and as CSV built from
that same list; every value verbatim from the service. Rows: totals
(tender/day empty), then per-tender, then per-day (paired with
``prior_day``), each for refund_count and total. Money = Decimal
strings to two places, counts = integers, None percent = empty.
"""
import csv
import io
from decimal import Decimal

from .prior_refund_report import FIGURES, prior_refund_report

__all__ = ["EXPORT_FIELDNAMES", "export_prior_refund_report",
           "export_prior_refund_report_csv", "export_prior_refund_report_rows",
           "prior_refund_report_csv", "prior_refund_report_export_row"]
EXPORT_FIELDNAMES = [
    "salon_id", "start", "end", "prior_start", "prior_end",
    "figure", "tender", "day", "prior_day",
    "current", "prior", "delta", "percent_change"]
_CENTS = Decimal("0.01")


def _money(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _value(figure, value):
    if value is None:
        return ""
    return str(int(value)) if figure == "refund_count" else _money(value)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else (value or "")


def prior_refund_report_export_row(figure, tender, day, prior_day, delta, result):
    return {
        "salon_id": result.salon_id,
        "start": _iso(result.start), "end": _iso(result.end),
        "prior_start": _iso(result.prior_start),
        "prior_end": _iso(result.prior_end),
        "figure": figure, "tender": tender,
        "day": _iso(day), "prior_day": _iso(prior_day),
        "current": _value(figure, delta.current),
        "prior": _value(figure, delta.prior),
        "delta": _value(figure, delta.delta),
        "percent_change": _money(delta.percent_change)}


def export_prior_refund_report(salon, start=None, end=None, **kwargs):
    """Return the prior refund-report comparison as dict rows."""
    result = prior_refund_report(salon, start, end, **kwargs)
    rows = [prior_refund_report_export_row(
        name, "", "", "", getattr(result, name), result) for name in FIGURES]
    for entry in result.entries:
        rows += [prior_refund_report_export_row(
            name, entry.tender, "", "", getattr(entry, name), result)
            for name in FIGURES]
    for entry in result.day_entries:
        rows += [prior_refund_report_export_row(
            name, "", entry.day, entry.prior_day, getattr(entry, name),
            result) for name in FIGURES]
    return rows


def export_prior_refund_report_csv(salon, start=None, end=None, **kwargs):
    """Return :func:`export_prior_refund_report` as a CSV string."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for record in export_prior_refund_report(salon, start, end, **kwargs):
        writer.writerow(record)
    return buffer.getvalue()


export_prior_refund_report_rows = export_prior_refund_report
prior_refund_report_csv = export_prior_refund_report_csv
