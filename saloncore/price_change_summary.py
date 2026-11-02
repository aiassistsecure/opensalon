"""Price-change window summary with prior-period comparison.

Backend only — no views, templates, or UI. Read-only. Aggregates
the stored :class:`~saloncore.models.PriceChange` ledger rows
verbatim over a window, alongside the equal-length prior window
immediately before it. Every figure derives from stored ledger
rows read through :mod:`saloncore.price_change_export`'s ledger
access (``_changes_in_range`` — salon isolation, chronological
order); prices are never recomputed from ``ServicePrice``.

Window figures: ``change_count`` (all rows), ``increase_count``
/ ``decrease_count`` (rows whose stored ``old_amount`` is present
and below / above ``new_amount``; a row with no old amount, or
with ``new == old``, is neither), ``net_amount_delta`` (sum of
``new_amount - old_amount`` over rows where old is present,
Decimal), and per-service counts in ``by_service`` (ordered by
service name, then id). Each figure carries ``current``,
``prior``, ``delta`` and ``percent_change`` (Decimal, two
places, ROUND_HALF_UP), ``None`` when prior is zero. Range
semantics: ``start`` / ``end`` are required inclusive local-date
bounds (``date`` or ``datetime``, datetimes reduced to their
local date, as in sibling summaries); a missing, non-date, or
reversed window raises ``ValueError``.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from saloncore.price_change_export import _changes_in_range

__all__ = ["MetricDelta", "CountDelta", "MoneyDelta", "WindowSummary",
           "ServiceChangeDelta", "PriceChangeSummary",
           "PriceChangeSummaryReport", "price_change_summary",
           "price_change_window_summary", "get_price_change_summary"]
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")


@dataclass(frozen=True)
class MetricDelta:
    """One metric in both periods, with its change."""

    component: str
    current: object = 0
    prior: object = 0
    delta: object = 0
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

CountDelta = MetricDelta
MoneyDelta = MetricDelta


def _pct_change(current, prior):
    current, prior = Decimal(current), Decimal(prior)
    if prior == 0:
        return None
    return ((current - prior) / prior * 100).quantize(
        _CENT, rounding=ROUND_HALF_UP)


def _count_delta(name, current, prior):
    current, prior = int(current), int(prior)
    return MetricDelta(name, current, prior, current - prior,
                       _pct_change(current, prior))


def _money_delta(name, current, prior):
    current = Decimal(current).quantize(_CENT, rounding=ROUND_HALF_UP)
    prior = Decimal(prior).quantize(_CENT, rounding=ROUND_HALF_UP)
    return MetricDelta(name, current, prior,
                       (current - prior).quantize(_CENT, rounding=ROUND_HALF_UP),
                       _pct_change(current, prior))


def _resolve_range(start, end):
    if start is None or end is None:
        raise ValueError("a start and an end date are required")

    def _as_date(value):
        if isinstance(value, datetime):
            return timezone.localtime(value).date() if timezone.is_aware(value) \
                else value.date()
        if isinstance(value, date):
            return value
        raise ValueError("range bounds must be a date or datetime")

    first, last = _as_date(start), _as_date(end)
    if last < first:
        raise ValueError("range end must not be before range start")
    return first, last


@dataclass(frozen=True)
class WindowSummary:
    """Ledger totals over one inclusive window (one source of truth)."""

    start_date: date = None
    end_date: date = None
    change_count: int = 0
    increase_count: int = 0
    decrease_count: int = 0
    net_amount_delta: Decimal = _ZERO
    by_service: list = field(default_factory=list)

    @property
    def total(self): return self.change_count

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "change_count": self.change_count,
                "increase_count": self.increase_count,
                "decrease_count": self.decrease_count,
                "net_amount_delta": self.net_amount_delta,
                "by_service": [dict(r) for r in self.by_service]}


def _window_summary(salon, first, last):
    services, change_count, increase_count, decrease_count, net = {}, 0, 0, 0, _ZERO
    for change in _changes_in_range(salon, first, last):
        service = change.service_price.service
        row = services.get(service.pk)
        if row is None:
            row = {"service_id": service.pk, "service_name": service.name,
                   "change_count": 0, "increase_count": 0, "decrease_count": 0,
                   "net_amount_delta": _ZERO}
            services[service.pk] = row
        change_count += 1
        row["change_count"] += 1
        if change.old_amount is not None:
            delta = change.new_amount - change.old_amount
            net += delta
            row["net_amount_delta"] += delta
            if delta > 0:
                increase_count += 1
                row["increase_count"] += 1
            elif delta < 0:
                decrease_count += 1
                row["decrease_count"] += 1
    by_service = sorted(services.values(),
                        key=lambda r: (r["service_name"], r["service_id"]))
    for row in by_service:
        row["net_amount_delta"] = row["net_amount_delta"].quantize(
            _CENT, rounding=ROUND_HALF_UP)
    return WindowSummary(first, last, change_count, increase_count,
                         decrease_count,
                         net.quantize(_CENT, rounding=ROUND_HALF_UP), by_service)


@dataclass(frozen=True)
class ServiceChangeDelta:
    """One service's price-change totals in both periods."""

    service_id: int = None
    service_name: str = ""
    current: object = None
    prior: object = None
    change_count: MetricDelta = None
    increase_count: MetricDelta = None
    decrease_count: MetricDelta = None
    net_amount_delta: MetricDelta = None

    @property
    def name(self): return self.service_name

    def as_dict(self):
        return {"service_id": self.service_id, "service_name": self.service_name,
                "change_count": self.change_count.as_dict(),
                "increase_count": self.increase_count.as_dict(),
                "decrease_count": self.decrease_count.as_dict(),
                "net_amount_delta": self.net_amount_delta.as_dict()}


_EMPTY_ROW = {"change_count": 0, "increase_count": 0, "decrease_count": 0,
              "net_amount_delta": _ZERO}


@dataclass(frozen=True)
class PriceChangeSummary:
    """Price-change summary comparison: current window vs prior."""

    salon_id: int = None
    start_date: date = None
    end_date: date = None
    prior_start_date: date = None
    prior_end_date: date = None
    current: object = None
    prior: object = None
    change_count: MetricDelta = None
    increase_count: MetricDelta = None
    decrease_count: MetricDelta = None
    net_amount_delta: MetricDelta = None
    by_service: list = field(default_factory=list)

    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    length = days
    per_service = property(lambda self: self.by_service)  # noqa: E731

    def for_service(self, service):
        key = getattr(service, "pk", service)
        return next((r for r in self.by_service if r.service_id == key), None)

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        return {"salon_id": self.salon_id, "start_date": iso(self.start_date),
                "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                "change_count": self.change_count.as_dict(),
                "increase_count": self.increase_count.as_dict(),
                "decrease_count": self.decrease_count.as_dict(),
                "net_amount_delta": self.net_amount_delta.as_dict(),
                "by_service": [r.as_dict() for r in self.by_service]}

    __iter__ = lambda self: iter(self.by_service)  # noqa: E731
    __len__ = lambda self: len(self.by_service)  # noqa: E731

PriceChangeSummaryReport = PriceChangeSummary


def price_change_summary(salon, start, end):
    """Return the price-change summary comparison for ``salon``.

    ``start`` / ``end`` are the current window's inclusive
    local-date bounds; the prior period is the equal-length
    window immediately before it. A missing or reversed window
    raises ``ValueError``. Figures come only from stored
    ``PriceChange`` rows. Records nothing.
    """
    first, last = _resolve_range(start, end)
    length = (last - first).days + 1
    prior_end = first - timedelta(days=1)
    prior_start = first - timedelta(days=length)
    current = _window_summary(salon, first, last)
    prior = _window_summary(salon, prior_start, prior_end)
    cur_rows = {r["service_id"]: r for r in current.by_service}
    pri_rows = {r["service_id"]: r for r in prior.by_service}
    meta = {}
    for source in (current.by_service, prior.by_service):
        for row in source:
            meta[row["service_id"]] = row
    by_service = []
    for sid in sorted(meta, key=lambda s: (meta[s]["service_name"], s)):
        cur, pri = cur_rows.get(sid, _EMPTY_ROW), pri_rows.get(sid, _EMPTY_ROW)
        by_service.append(ServiceChangeDelta(
            service_id=sid, service_name=meta[sid]["service_name"],
            current=cur if sid in cur_rows else None,
            prior=pri if sid in pri_rows else None,
            change_count=_count_delta("change_count", cur["change_count"],
                                      pri["change_count"]),
            increase_count=_count_delta("increase_count", cur["increase_count"],
                                        pri["increase_count"]),
            decrease_count=_count_delta("decrease_count", cur["decrease_count"],
                                        pri["decrease_count"]),
            net_amount_delta=_money_delta("net_amount_delta",
                                          cur["net_amount_delta"],
                                          pri["net_amount_delta"])))
    return PriceChangeSummary(
        salon_id=getattr(salon, "pk", salon), start_date=first, end_date=last,
        prior_start_date=prior_start, prior_end_date=prior_end,
        current=current, prior=prior,
        change_count=_count_delta("change_count", current.change_count,
                                  prior.change_count),
        increase_count=_count_delta("increase_count", current.increase_count,
                                    prior.increase_count),
        decrease_count=_count_delta("decrease_count", current.decrease_count,
                                    prior.decrease_count),
        net_amount_delta=_money_delta("net_amount_delta",
                                      current.net_amount_delta,
                                      prior.net_amount_delta),
        by_service=by_service)


#: Aliases, mirroring the naming convenience in sibling services.
price_change_window_summary = price_change_summary
get_price_change_summary = price_change_summary
