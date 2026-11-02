"""Prior-period comparison for service popularity + client value.

Backend only — no views, templates, or UI. Nothing is stored.
Extends :mod:`insights.prior_period` to the per-service
appointment counts of :mod:`insights.popularity` and the
per-client settled revenue of :mod:`insights.client_value`,
mirroring :mod:`insights.prior_staff_service`: the prior
period is the equal-length window immediately before the
current one; figures come verbatim from those services, never
re-derived from ``Appointment`` or ``Sale`` rows;
``percent_change`` is a Decimal quantised to two places and
is ``None`` when the prior value is zero (the absolute
``delta`` is always present); a reversed window raises
``ValueError``. Rows present in only one period appear with
the missing side zero. Popularity rows key by linked service
or snapshot name, client rows by client, as the services
group them. Client-value rows carry attributed revenue only;
the services' unattributed bucket is exposed separately on
the comparison as ``unattributed``. Rows order by current
total descending, then name ascending. The CSV helpers
follow :mod:`insights.prior_period_export`: they render a
comparison verbatim (Exit Principle), money and percentages
to two decimal places, ``None`` percent as empty.
"""
import csv
import io
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from .client_value import client_value
from .popularity import service_popularity
from .prior_period import ComponentDelta, _as_window_date, _delta
from .services import ZERO

__all__ = [
    "PopularityPriorDelta", "ClientValuePriorDelta",
    "PriorPopularityComparison", "PriorClientValueComparison",
    "prior_period_popularity", "prior_period_client_value",
    "compare_popularity", "compare_client_value",
    "PRIOR_POPULARITY_FIELDNAMES", "PRIOR_CLIENT_VALUE_FIELDNAMES",
    "export_prior_popularity_csv", "export_prior_client_value_csv",
]

_CENTS = Decimal("0.01")


def _count_delta(component, current, prior):
    return _delta(component, Decimal(current), Decimal(prior))


@dataclass(frozen=True)
class PopularityPriorDelta:
    """One service's appointment counts in both periods."""

    service: object | None
    service_name: str
    current: object | None
    prior: object | None
    completed: ComponentDelta
    booked: ComponentDelta
    cancelled_no_show: ComponentDelta
    total: ComponentDelta

    @property
    def current_total_count(self):
        return self.current.total_count if self.current else 0

    @property
    def prior_total_count(self):
        return self.prior.total_count if self.prior else 0

    @property
    def current_completed_count(self):
        return self.current.completed_count if self.current else 0

    @property
    def prior_completed_count(self):
        return self.prior.completed_count if self.prior else 0


@dataclass(frozen=True)
class ClientValuePriorDelta:
    """One client's settled revenue in both periods."""

    client: object | None
    display_name: str
    current: object | None
    prior: object | None
    revenue: ComponentDelta
    current_sale_count: int
    prior_sale_count: int

    @property
    def sale_count_delta(self):
        return self.current_sale_count - self.prior_sale_count


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


class PriorPopularityComparison(_Comparison):
    """Current vs prior per-service popularity delta rows."""


class PriorClientValueComparison(_Comparison):
    """Current vs prior per-client value delta rows.

    ``unattributed`` is the delta of the two periods'
    unattributed totals (see :mod:`insights.client_value`).
    """

    def __init__(self, rows, *, unattributed,
                 unattributed_current_sale_count,
                 unattributed_prior_sale_count, **kwargs):
        super().__init__(rows, **kwargs)
        self.unattributed = unattributed
        self.unattributed_current_sale_count = (
            unattributed_current_sale_count)
        self.unattributed_prior_sale_count = (
            unattributed_prior_sale_count)


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
    return start, end, start - timedelta(days=length), \
        start - timedelta(days=1)


def prior_period_popularity(salon, start_date=None, end_date=None,
                            **kwargs):
    """Return per-service popularity for current vs prior period."""
    start, end, p_start, p_end = _window(
        salon, start_date, end_date, kwargs)
    current = service_popularity(salon, start, end)
    prior = service_popularity(salon, p_start, p_end)

    def key(row):
        return (("service", row.service_id)
                if row.service_id is not None
                else ("snapshot", row.service_name))

    cur = {key(r): r for r in current}
    pri = {key(r): r for r in prior}
    rows = []
    for k in dict.fromkeys([*cur, *pri]):
        c, p = cur.get(k), pri.get(k)
        ref = c or p
        rows.append(PopularityPriorDelta(
            service=ref.service, service_name=ref.service_name,
            current=c, prior=p,
            completed=_count_delta(
                "completed", c.completed_count if c else 0,
                p.completed_count if p else 0),
            booked=_count_delta(
                "booked", c.booked_count if c else 0,
                p.booked_count if p else 0),
            cancelled_no_show=_count_delta(
                "cancelled_no_show",
                c.cancelled_no_show_count if c else 0,
                p.cancelled_no_show_count if p else 0),
            total=_count_delta(
                "total", c.total_count if c else 0,
                p.total_count if p else 0),
        ))
    rows.sort(key=lambda r: (-r.total.current, r.service_name))
    return PriorPopularityComparison(
        rows, start_date=start, end_date=end,
        prior_start_date=p_start, prior_end_date=p_end)


def prior_period_client_value(salon, start_date=None, end_date=None,
                              **kwargs):
    """Return per-client value for the current vs prior period."""
    start, end, p_start, p_end = _window(
        salon, start_date, end_date, kwargs)
    current = client_value(salon, start, end)
    prior = client_value(salon, p_start, p_end)
    cur = {r.client_id: r for r in current.rows}
    pri = {r.client_id: r for r in prior.rows}
    rows = []
    for k in dict.fromkeys([*cur, *pri]):
        c, p = cur.get(k), pri.get(k)
        ref = c or p
        rows.append(ClientValuePriorDelta(
            client=ref.client, display_name=ref.display_name,
            current=c, prior=p,
            revenue=_delta("revenue", c.total if c else ZERO,
                           p.total if p else ZERO),
            current_sale_count=c.sale_count if c else 0,
            prior_sale_count=p.sale_count if p else 0,
        ))
    rows.sort(key=lambda r: (-r.revenue.current, r.display_name))
    return PriorClientValueComparison(
        rows, start_date=start, end_date=end,
        prior_start_date=p_start, prior_end_date=p_end,
        unattributed=_delta(
            "unattributed", current.unattributed_total,
            prior.unattributed_total),
        unattributed_current_sale_count=(
            current.unattributed_sale_count),
        unattributed_prior_sale_count=prior.unattributed_sale_count)


compare_popularity = prior_period_popularity
compare_client_value = prior_period_client_value

PRIOR_POPULARITY_FIELDNAMES = [
    "service_name", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "current", "prior",
    "delta", "percent_change", "current_completed_count",
    "prior_completed_count", "current_total_count",
    "prior_total_count",
]
PRIOR_CLIENT_VALUE_FIELDNAMES = [
    "client_name", "current_start_date", "current_end_date",
    "prior_start_date", "prior_end_date", "current", "prior",
    "delta", "percent_change", "current_sale_count",
    "prior_sale_count",
]


def _money(value):
    return str(Decimal(value).quantize(_CENTS))


def _pct(value):
    return "" if value is None else str(Decimal(value).quantize(_CENTS))


def _count(value):
    return str(int(Decimal(value)))


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


def export_prior_popularity_csv(salon, start_date=None, end_date=None,
                                **kwargs):
    """Return the popularity prior-period comparison as CSV."""
    result = prior_period_popularity(salon, start_date, end_date,
                                     **kwargs)
    return _write([{
        "service_name": r.service_name, **_bounds(result),
        "current": _count(r.total.current),
        "prior": _count(r.total.prior),
        "delta": _count(r.total.delta),
        "percent_change": _pct(r.total.percent_change),
        "current_completed_count": r.current_completed_count,
        "prior_completed_count": r.prior_completed_count,
        "current_total_count": r.current_total_count,
        "prior_total_count": r.prior_total_count,
    } for r in result], PRIOR_POPULARITY_FIELDNAMES)


def export_prior_client_value_csv(salon, start_date=None,
                                  end_date=None, **kwargs):
    """Return the client-value prior-period comparison as CSV."""
    result = prior_period_client_value(salon, start_date, end_date,
                                       **kwargs)
    return _write([{
        "client_name": r.display_name, **_bounds(result),
        "current": _money(r.revenue.current),
        "prior": _money(r.revenue.prior),
        "delta": _money(r.revenue.delta),
        "percent_change": _pct(r.revenue.percent_change),
        "current_sale_count": r.current_sale_count,
        "prior_sale_count": r.prior_sale_count,
    } for r in result], PRIOR_CLIENT_VALUE_FIELDNAMES)
