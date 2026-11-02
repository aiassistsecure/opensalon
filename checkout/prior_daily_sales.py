"""Prior for daily sales summary (same-weekday comparison).

Backend only, read-only. Built ON TOP of
:func:`checkout.summary.daily_sales_summary` — figures for both
days are that service's verbatim (sale count, ``gross_total``,
``discount_total``, ``net_total``, the service/retail/
series kind split, and ``item_count``); nothing is recomputed
here. The prior for
a single day is the same weekday one week earlier (a 7-day
offset — the house definition for single-day reports, per
:mod:`bookings.prior_day_load`). Each figure carries
``current``, ``prior``, ``delta`` and ``percent_change``
(Decimal, two places, ROUND_HALF_UP), ``None`` when the prior
figure is zero. Money stays Decimal. Missing salon/date raises
``ValueError``. Provider-agnostic core.
"""
import datetime
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .summary import daily_sales_summary

_CENTS = Decimal("0.01")
__all__ = ["MetricDelta", "FigureDelta", "PriorDailySales",
           "PriorDailySalesComparison", "PriorDailySalesReport",
           "prior_daily_sales", "prior_daily_sales_report",
           "prior_same_weekday_daily_sales", "compare_daily_sales",
           "get_prior_daily_sales"]
FIGURES = ("sales_count", "gross_total", "discount_total", "net_total",
           "service_total", "retail_total", "series_total", "item_count")
_COUNTS = ("sales_count", "item_count")
KIND_FIGURES = ("service_total", "retail_total", "series_total")
_KINDS = {"service_total": "service", "retail_total": "product",
          "series_total": "series"}


def _pct_change(current, prior):
    if prior is None or Decimal(prior) == 0:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior)
            * 100).quantize(_CENTS, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MetricDelta:
    """One figure in both days, with its change."""

    component: str
    current: object = None
    prior: object = None
    delta: object = None
    percent_change: Decimal | None = None

    @property
    def name(self): return self.component
    @property
    def previous(self): return self.prior
    @property
    def change(self): return self.delta
    @property
    def pct_change(self): return self.percent_change

    def as_dict(self):
        return {"component": self.component, "current": self.current,
                "prior": self.prior, "delta": self.delta,
                "percent_change": self.percent_change}


FigureDelta = MetricDelta


def _money_delta(name, current, prior):
    current, prior = Decimal(current), Decimal(prior)
    return MetricDelta(name, current, prior,
                       (current - prior).quantize(_CENTS, rounding=ROUND_HALF_UP),
                       _pct_change(current, prior))


def _count_delta(name, current, prior):
    current, prior = int(current), int(prior)
    return MetricDelta(name, current, prior, current - prior,
                       _pct_change(current, prior))


@dataclass(frozen=True)
class PriorDailySales:
    """Current vs same-weekday-prior daily sales summaries."""

    salon: object = None
    date: object = None
    prior_date: object = None
    current: object = None
    prior: object = None
    sales_count: MetricDelta = None
    gross_total: MetricDelta = None
    discount_total: MetricDelta = None
    net_total: MetricDelta = None
    service_total: MetricDelta = None
    retail_total: MetricDelta = None
    series_total: MetricDelta = None
    item_count: MetricDelta = None
    by_kind: dict = field(default_factory=dict)

    @property
    def salon_id(self): return getattr(self.salon, "pk", self.salon)
    @property
    def day(self): return self.date
    @property
    def previous(self): return self.prior
    @property
    def current_summary(self): return self.current
    @property
    def prior_summary(self): return self.prior
    @property
    def sale_count(self): return self.sales_count

    def __getitem__(self, key):
        if key in _KINDS.values():
            name = next(n for n, k in _KINDS.items() if k == key)
            return getattr(self, name)
        return self.by_kind[key] if key in self.by_kind else getattr(self, key)

    def as_dict(self):
        return {"date": self.date.isoformat() if self.date else None,
                "prior_date": self.prior_date.isoformat() if self.prior_date else None,
                **{name: getattr(self, name).as_dict() for name in FIGURES}}


PriorDailySalesComparison = PriorDailySales
PriorDailySalesReport = PriorDailySales


def _tz(salon):
    try:
        return ZoneInfo(getattr(salon, "timezone", None) or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _as_date(value, tz):
    if isinstance(value, datetime.datetime):
        return value.astimezone(tz).date() if value.tzinfo else value.date()
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value))


def prior_daily_sales(salon, day=None, **kwargs):
    """Return the :class:`PriorDailySales` for ``salon`` on ``day``.

    Prior day is ``day - 7 days`` (same weekday). ``day`` may
    also be passed as ``date=`` / ``date_from=`` / ``start_date=``.
    Raises ``ValueError`` if salon or date is missing/unparseable.
    """
    if day is None:
        day = (kwargs.pop("date", None) or kwargs.pop("date_from", None)
               or kwargs.pop("start_date", None) or kwargs.pop("start", None))
    if kwargs:
        raise TypeError(f"Unexpected arguments: {', '.join(sorted(kwargs))}")
    if salon is None:
        raise ValueError("prior_daily_sales needs a salon")
    if day is None:
        raise ValueError("prior_daily_sales needs a date")
    try:
        current_date = _as_date(day, _tz(salon))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid date {day!r}.") from exc
    prior_date = current_date - datetime.timedelta(days=7)
    current = daily_sales_summary(salon, current_date)
    prior = daily_sales_summary(salon, prior_date)
    deltas = {
        **{name: _count_delta(name, getattr(current, name),
                              getattr(prior, name))
           for name in _COUNTS},
        **{name: _money_delta(name, getattr(current, name), getattr(prior, name))
           for name in FIGURES if name not in _COUNTS},
    }
    return PriorDailySales(
        salon=salon, date=current_date, prior_date=prior_date,
        current=current, prior=prior, **deltas,
        by_kind={_KINDS[name]: deltas[name] for name in KIND_FIGURES})


#: Aliases, mirroring sibling services.
prior_daily_sales_report = prior_daily_sales
prior_same_weekday_daily_sales = prior_daily_sales
compare_daily_sales = prior_daily_sales
get_prior_daily_sales = prior_daily_sales
