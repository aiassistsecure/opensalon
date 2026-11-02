"""Prior-period send totals comparison CSV export.

Backend only -- no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the comparison from
:mod:`messaging.prior_send_totals` verbatim -- it never
recomputes a figure, delta, or percentage. One row per metric:
``total``, ``reminder_total``, ``campaign_total``, then per-channel
rows for reminder, campaign, and combined sends. Columns:
``metric``, current/prior window bounds, ``current``, ``prior``,
``delta``, ``percent_change``. ``percent_change`` renders to two
places, never via a float; ``None`` renders empty. Lines ``"\\n"``.
"""
import csv
import io
from decimal import Decimal

from .prior_send_totals import prior_send_totals

__all__ = [
    "PRIOR_SEND_TOTALS_FIELDNAMES",
    "PRIOR_SEND_TOTALS_EXPORT_FIELDNAMES", "EXPORT_FIELDNAMES",
    "export_prior_send_totals_csv", "export_prior_send_totals_comparison_csv",
    "prior_send_totals_csv",
]

PRIOR_SEND_TOTALS_FIELDNAMES = [
    "metric", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "current", "prior",
    "delta", "percent_change",
]
PRIOR_SEND_TOTALS_EXPORT_FIELDNAMES = PRIOR_SEND_TOTALS_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_SEND_TOTALS_FIELDNAMES
_CENTS = Decimal("0.01")

def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))

def _metrics(result):
    yield "total", result.total
    yield "reminder_total", result.reminder_total
    yield "campaign_total", result.campaign_total
    for ch, delta in result.reminder_by_channel.items():
        yield f"reminder_{ch}", delta
    for ch, delta in result.campaign_by_channel.items():
        yield f"campaign_{ch}", delta
    for ch, delta in result.combined_by_channel.items():
        yield f"combined_{ch}", delta

def export_prior_send_totals_csv(salon, start=None, end=None, **kwargs):
    """Return ``salon``'s prior-period send totals as CSV.

    Args mirror :func:`messaging.prior_send_totals.prior_send_totals`
    exactly; its values are rendered unchanged.
    """
    result = prior_send_totals(salon, start, end, **kwargs)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_SEND_TOTALS_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for name, comp in _metrics(result):
        writer.writerow({
            "metric": name,
            "current_start_date": result.start_date.isoformat(),
            "current_end_date": result.end_date.isoformat(),
            "prior_start_date": result.prior_start_date.isoformat(),
            "prior_end_date": result.prior_end_date.isoformat(),
            "current": comp.current, "prior": comp.prior,
            "delta": comp.delta, "percent_change": _pct(comp.percent_change),
        })
    return buffer.getvalue()

#: Aliases, mirroring the naming convenience in sibling services.
export_prior_send_totals_comparison_csv = export_prior_send_totals_csv
prior_send_totals_csv = export_prior_send_totals_csv
