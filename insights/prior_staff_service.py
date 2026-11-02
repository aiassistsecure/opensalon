"""Prior-period comparison for per-staff and per-service revenue.

Backend only — no views, templates, or UI. Nothing is stored.
Extends :mod:`insights.prior_period` to the per-staff breakdown
of :mod:`insights.staff_revenue` and the per-service breakdown
of :mod:`insights.service_revenue`, mirroring its conventions:
the prior period is the equal-length window immediately before
the current one; revenue comes verbatim from those services,
never re-derived from ``Sale`` rows; ``percent_change`` is a
Decimal quantised to two places and is ``None`` when the prior
value is zero (the absolute ``delta`` is always present); a
reversed window raises ``ValueError``. Rows present in only one
period appear with the missing side zero; staff rows key by
staff member (unattributed is its own row) and service rows key
by linked service or snapshot name, as the services group them.
Rows order by current total descending, then name ascending.
The CSV helpers follow :mod:`insights.prior_period_export`:
they render a comparison verbatim (Exit Principle), money and
percentages to two decimal places, ``None`` percent as empty.
"""
import csv
import io
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .prior_period import ComponentDelta, _as_window_date, _delta
from .service_revenue import revenue_by_service
from .services import ZERO
from .staff_revenue import UNATTRIBUTED_NAME, revenue_by_staff

__all__ = [
    "StaffPriorDelta", "ServicePriorDelta",
    "PriorStaffComparison", "PriorServiceComparison",
    "prior_period_staff_revenue", "prior_period_service_revenue",
    "compare_staff_revenue", "compare_service_revenue",
    "PRIOR_STAFF_FIELDNAMES", "PRIOR_SERVICE_FIELDNAMES",
    "export_prior_staff_csv", "export_prior_service_csv",
]

_CENTS = Decimal("0.01")


@dataclass(frozen=True)
class StaffPriorDelta:
    """One staff row in both periods, with its change."""

    staff: object | None
    display_name: str
    current: object | None
    prior: object | None
    service: ComponentDelta
    retail: ComponentDelta
    series: ComponentDelta
    total: ComponentDelta
    current_sale_count: int
    prior_sale_count: int

    @property
    def sale_count_delta(self):
        return self.current_sale_count - self.prior_sale_count


@dataclass(frozen=True)
class ServicePriorDelta:
    """One service row in both periods, with its change."""

    service: object | None
    service_name: str
    current: object | None
    prior: object | None
    revenue: ComponentDelta
    current_quantity: int
    prior_quantity: int
    current_sale_count: int
    prior_sale_count: int

    @property
    def name(self):
        return self.service_name


class _Comparison(list):
    """A list of delta rows, oldest-period bounds attached."""

    def __init__(self, rows, *, start_date, end_date,
                 prior_start_date, prior_end_date):
        super().__init__(rows)
        self.start_date = start_date
        self.end_date = end_date
        self.prior_start_date = prior_start_date
        self.prior_end_date = prior_end_date
        self.days = (end_date - start_date).days + 1


class PriorStaffComparison(_Comparison):
    """Current vs prior per-staff revenue delta rows."""


class PriorServiceComparison(_Comparison):
    """Current vs prior per-service revenue delta rows."""


def _window(salon, start_date, end_date, kwargs):
    if start_date is None:
        start_date = kwargs.pop("start", kwargs.pop("since", None))
    if end_date is None:
        end_date = kwargs.pop("end", kwargs.pop("until", None))
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(kwargs)}")
    if start_date is None or end_date is None:
        raise ValueError("Both start_date and end_date are required.")
    start = _as_window_date(start_date, salon)
    end = _as_window_date(end_date, salon)
    if end < start:
        raise ValueError("end_date must be on or after start_date.")
    length = (end - start).days + 1
    return start, end, start - timedelta(days=length), start - timedelta(days=1)


def prior_period_staff_revenue(salon, start_date=None, end_date=None,
                               **kwargs):
    """Return per-staff revenue for the current vs prior period."""
    start, end, p_start, p_end = _window(salon, start_date, end_date, kwargs)
    current = revenue_by_staff(salon, start, end)
    prior = revenue_by_staff(salon, p_start, p_end)
    cur = {r.staff.pk if r.staff else None: r for r in current}
    pri = {r.staff.pk if r.staff else None: r for r in prior}
    rows = []
    for key in dict.fromkeys([*cur, *pri]):
        c, p = cur.get(key), pri.get(key)
        ref = c or p
        rows.append(StaffPriorDelta(
            staff=ref.staff, display_name=ref.display_name,
            current=c, prior=p,
            service=_delta("service", c.service_revenue if c else ZERO,
                           p.service_revenue if p else ZERO),
            retail=_delta("retail", c.retail_revenue if c else ZERO,
                          p.retail_revenue if p else ZERO),
            series=_delta("series", c.series_revenue if c else ZERO,
                          p.series_revenue if p else ZERO),
            total=_delta("total", c.total if c else ZERO,
                         p.total if p else ZERO),
            current_sale_count=c.sale_count if c else 0,
            prior_sale_count=p.sale_count if p else 0,
        ))
    rows.sort(key=lambda r: (-r.total.current, r.display_name))
    return PriorStaffComparison(
        rows, start_date=start, end_date=end,
        prior_start_date=p_start, prior_end_date=p_end)


def prior_period_service_revenue(salon, start_date=None, end_date=None,
                                 **kwargs):
    """Return per-service revenue for the current vs prior period."""
    start, end, p_start, p_end = _window(salon, start_date, end_date, kwargs)
    current = revenue_by_service(salon, start, end)
    prior = revenue_by_service(salon, p_start, p_end)

    def key(row):
        return (("service", row.service_id) if row.service_id is not None
                else ("snapshot", row.service_name))

    cur = {key(r): r for r in current}
    pri = {key(r): r for r in prior}
    rows = []
    for k in dict.fromkeys([*cur, *pri]):
        c, p = cur.get(k), pri.get(k)
        ref = c or p
        rows.append(ServicePriorDelta(
            service=ref.service, service_name=ref.service_name,
            current=c, prior=p,
            revenue=_delta("revenue", c.revenue if c else ZERO,
                           p.revenue if p else ZERO),
            current_quantity=c.quantity if c else 0,
            prior_quantity=p.quantity if p else 0,
            current_sale_count=c.sale_count if c else 0,
            prior_sale_count=p.sale_count if p else 0,
        ))
    rows.sort(key=lambda r: (-r.revenue.current, r.service_name))
    return PriorServiceComparison(
        rows, start_date=start, end_date=end,
        prior_start_date=p_start, prior_end_date=p_end)


compare_staff_revenue = prior_period_staff_revenue
compare_service_revenue = prior_period_service_revenue

PRIOR_STAFF_FIELDNAMES = [
    "staff_name", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "current", "prior",
    "delta", "percent_change", "current_sale_count", "prior_sale_count",
]
PRIOR_SERVICE_FIELDNAMES = [
    "service_name", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "current", "prior",
    "delta", "percent_change", "current_quantity", "prior_quantity",
    "current_sale_count", "prior_sale_count",
]


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _write(rows, fieldnames):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames,
                            lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def _bounds(result):
    return {
        "current_start_date": result.start_date.isoformat(),
        "current_end_date": result.end_date.isoformat(),
        "prior_start_date": result.prior_start_date.isoformat(),
        "prior_end_date": result.prior_end_date.isoformat(),
    }


def export_prior_staff_csv(salon, start_date=None, end_date=None, **kwargs):
    """Return the per-staff prior-period comparison as a CSV string."""
    result = prior_period_staff_revenue(salon, start_date, end_date, **kwargs)
    return _write([{
        "staff_name": r.display_name, **_bounds(result),
        "current": _money(r.total.current), "prior": _money(r.total.prior),
        "delta": _money(r.total.delta),
        "percent_change": _pct(r.total.percent_change),
        "current_sale_count": r.current_sale_count,
        "prior_sale_count": r.prior_sale_count,
    } for r in result], PRIOR_STAFF_FIELDNAMES)


def export_prior_service_csv(salon, start_date=None, end_date=None,
                             **kwargs):
    """Return the per-service prior-period comparison as a CSV string."""
    result = prior_period_service_revenue(
        salon, start_date, end_date, **kwargs)
    return _write([{
        "service_name": r.service_name, **_bounds(result),
        "current": _money(r.revenue.current),
        "prior": _money(r.revenue.prior),
        "delta": _money(r.revenue.delta),
        "percent_change": _pct(r.revenue.percent_change),
        "current_quantity": r.current_quantity,
        "prior_quantity": r.prior_quantity,
        "current_sale_count": r.current_sale_count,
        "prior_sale_count": r.prior_sale_count,
    } for r in result], PRIOR_SERVICE_FIELDNAMES)
