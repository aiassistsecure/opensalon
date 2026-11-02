"""Prior-period refunds/net comparison CSV export service.

Backend only — no views, templates, or UI. Read-only.

Founding rule (Exit Principle): anything a salon can enter, it
can fully export. This module exports the comparison from
:mod:`insights.prior_refunds_net` verbatim — it never recomputes
a figure, a delta, or a percentage. One row per metric
(``gross``, ``refunds``, ``net``, ``refund_count``), in that
order, in the sibling style of the other prior-period exports.

Columns: ``metric``, the current and prior window bounds,
``current``, ``prior``, ``delta``, and ``percent_change``.
Money and percentages render to two decimal places, never via
a float; refund counts render as integers; a ``None`` percent
change (zero prior figure — see
:mod:`insights.prior_refunds_net`) renders as an empty string.
"""
import csv
import io
from decimal import Decimal

from insights.prior_refunds_net import prior_refunds_net

__all__ = [
    "PRIOR_REFUNDS_NET_FIELDNAMES",
    "PRIOR_REFUNDS_NET_EXPORT_FIELDNAMES",
    "EXPORT_FIELDNAMES",
    "export_prior_refunds_net_csv",
    "export_prior_refunds_net_comparison_csv",
    "prior_refunds_net_csv",
]

PRIOR_REFUNDS_NET_FIELDNAMES = [
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
PRIOR_REFUNDS_NET_EXPORT_FIELDNAMES = PRIOR_REFUNDS_NET_FIELDNAMES
EXPORT_FIELDNAMES = PRIOR_REFUNDS_NET_FIELDNAMES

_CENTS = Decimal("0.01")
_METRICS = ("gross", "refunds", "net", "refund_count")
_COUNTS = ("refund_count",)


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _count(value):
    return str(int(Decimal(value)))


def export_prior_refunds_net_csv(salon, start_date=None, end_date=None,
                                 **kwargs):
    """Return ``salon``'s prior-period refunds/net comparison as CSV.

    Args mirror :func:`insights.prior_refunds_net.prior_refunds_net`
    exactly; its result's values are rendered unchanged.
    """
    result = prior_refunds_net(salon, start_date, end_date, **kwargs)

    def fmt(name, value):
        return _count(value) if name in _COUNTS else _money(value)

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PRIOR_REFUNDS_NET_FIELDNAMES,
        lineterminator="\n"
    )
    writer.writeheader()
    for name in _METRICS:
        comp = getattr(result, name)
        writer.writerow({
            "metric": name,
            "current_start_date": result.current.start_date.isoformat(),
            "current_end_date": result.current.end_date.isoformat(),
            "prior_start_date": result.prior.start_date.isoformat(),
            "prior_end_date": result.prior.end_date.isoformat(),
            "current": fmt(name, comp.current),
            "prior": fmt(name, comp.prior),
            "delta": fmt(name, comp.delta),
            "percent_change": _pct(comp.percent_change),
        })
    return buffer.getvalue()


#: Aliases, mirroring the naming convenience in sibling services.
export_prior_refunds_net_comparison_csv = export_prior_refunds_net_csv
prior_refunds_net_csv = export_prior_refunds_net_csv
