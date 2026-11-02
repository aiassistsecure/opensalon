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

Per-service rows also compare the duration figures of
:mod:`insights.service_revenue`, taken verbatim from its rows
for both windows (no new counting path): ``total_duration_minutes``
as a count delta (``Decimal(int)``, house convention) and
``revenue_per_hour`` as a money delta. Both deltas are ``None``
when either window's figure is ``None`` — a service with zero
or unknown duration has no honest total or per-hour figure, and
a row present in only one period has no per-hour figure for the
missing period — never faked as zero; the verbatim rows remain
on ``current`` / ``prior``. ``line_count`` is carried as a raw
current/prior int pair alongside the quantity/sale_count pairs.
``duration_minutes`` itself is NOT compared: it is the linked
service's current ``total_minutes``, the same value for both
windows by construction, so its delta would be structurally
zero; ``total_duration_minutes`` (duration x the window's own
quantity) is the honest per-window figure.
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


def _count_delta(component, current, prior):
    return _delta(component, Decimal(current), Decimal(prior))


def _total_duration_delta(current, prior):
    """Count delta for ``total_duration_minutes``, or ``None``.

    A missing row counts as zero only when the other window's
    verbatim total is known (its duration is known); when either
    window's total is ``None`` (zero/unknown duration) there is
    no honest delta, so the comparison is ``None``.
    """
    if current is not None:
        cur = current.total_duration_minutes
    else:
        cur = 0 if prior is not None and \
            prior.total_duration_minutes is not None else None
    if prior is not None:
        pri = prior.total_duration_minutes
    else:
        pri = 0 if current is not None and \
            current.total_duration_minutes is not None else None
    if cur is None or pri is None:
        return None
    return _count_delta("total_duration_minutes", cur, pri)


def _revenue_per_hour_delta(current, prior):
    """Money delta for ``revenue_per_hour``, or ``None``.

    ``None`` when either window's verbatim per-hour figure is
    ``None`` (zero/unknown duration, or the row is absent from
    that window so no time was sold there) — never faked.
    """
    if current is None or prior is None:
        return None
    if current.revenue_per_hour is None \
            or prior.revenue_per_hour is None:
        return None
    return _delta("revenue_per_hour", current.revenue_per_hour,
                  prior.revenue_per_hour)


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
    total_duration_minutes: ComponentDelta | None = None
    revenue_per_hour: ComponentDelta | None = None
    current_line_count: int = 0
    prior_line_count: int = 0

    @property
    def name(self):
        return self.service_name

    @property
    def line_count_delta(self):
        return self.current_line_count - self.prior_line_count


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
            total_duration_minutes=_total_duration_delta(c, p),
            revenue_per_hour=_revenue_per_hour_delta(c, p),
            current_line_count=c.line_count if c else 0,
            prior_line_count=p.line_count if p else 0,
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
    "current_line_count", "prior_line_count",
    "current_total_duration_minutes", "prior_total_duration_minutes",
    "total_duration_minutes_delta",
    "total_duration_minutes_percent_change",
    "current_revenue_per_hour", "prior_revenue_per_hour",
    "revenue_per_hour_delta", "revenue_per_hour_percent_change",
]


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _money_or_empty(value):
    return "" if value is None else _money(value)


def _count_or_empty(value):
    return "" if value is None else str(int(Decimal(value)))


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
    def service_row(r):
        duration = r.total_duration_minutes
        per_hour = r.revenue_per_hour
        return {
            "service_name": r.service_name, **_bounds(result),
            "current": _money(r.revenue.current),
            "prior": _money(r.revenue.prior),
            "delta": _money(r.revenue.delta),
            "percent_change": _pct(r.revenue.percent_change),
            "current_quantity": r.current_quantity,
            "prior_quantity": r.prior_quantity,
            "current_sale_count": r.current_sale_count,
            "prior_sale_count": r.prior_sale_count,
            "current_line_count": r.current_line_count,
            "prior_line_count": r.prior_line_count,
            "current_total_duration_minutes": _count_or_empty(
                duration.current if duration else None),
            "prior_total_duration_minutes": _count_or_empty(
                duration.prior if duration else None),
            "total_duration_minutes_delta": _count_or_empty(
                duration.delta if duration else None),
            "total_duration_minutes_percent_change": _pct(
                duration.percent_change if duration else None),
            # When the per-hour delta is None, render the verbatim
            # per-window figures (empty where a side has none).
            "current_revenue_per_hour": _money_or_empty(
                per_hour.current if per_hour else
                r.current.revenue_per_hour if r.current else None),
            "prior_revenue_per_hour": _money_or_empty(
                per_hour.prior if per_hour else
                r.prior.revenue_per_hour if r.prior else None),
            "revenue_per_hour_delta": _money_or_empty(
                per_hour.delta if per_hour else None),
            "revenue_per_hour_percent_change": _pct(
                per_hour.percent_change if per_hour else None),
        }

    return _write([service_row(r) for r in result],
                  PRIOR_SERVICE_FIELDNAMES)
