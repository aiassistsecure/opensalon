"""Prior-period comparison for the stock movement summary.

Backend only — no views, templates, or UI. Read-only. Built ON
TOP of :func:`catalog.movement_summary.movement_summary` —
figures for both windows are that service's verbatim; never
recomputed. For an inclusive current window ``[start, end]``
of ``length`` days, the prior period is ``[start - length,
start - 1]``. Range semantics are the underlying service's own
(reversed / missing / non-date bound raises its
``ValueError``); salon scope is optional, as there. Each
metric carries ``current``, ``prior``, ``delta`` and
``percent_change`` (Decimal, two places, ROUND_HALF_UP),
``None`` when prior is zero. ``by_product`` is the union of
both windows' rows (one-window products get zeros on the other
side), ordered by product name, then id. Negative sums are
reported as they stand, never clamped.
"""
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from catalog.movement_summary import movement_summary

__all__ = ["MetricDelta", "CountDelta", "MovementDelta", "ProductMovementDelta",
           "PriorMovementSummary", "PriorMovementSummaryReport",
           "prior_movement_summary", "prior_period_movement_summary",
           "compare_movement_summary", "get_prior_movement_summary"]
_CENT = Decimal("0.01")


@dataclass(frozen=True)
class MetricDelta:
    """One metric in both periods, with its change."""

    component: str
    current: int = 0
    prior: int = 0
    delta: int = 0
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
MovementDelta = MetricDelta


def _pct_change(current, prior):
    if not prior:
        return None
    return ((Decimal(current) - Decimal(prior)) / Decimal(prior) * 100
            ).quantize(_CENT, rounding=ROUND_HALF_UP)


def _delta(name, current, prior):
    current, prior = int(current), int(prior)
    return MetricDelta(name, current, prior, current - prior,
                       _pct_change(current, prior))


def _kind_deltas(prefix, current_by_kind, prior_by_kind):
    kinds = list(current_by_kind) + [
        kind for kind in prior_by_kind if kind not in current_by_kind]
    return {kind: _delta(f"{prefix}_{kind}", current_by_kind.get(kind, 0),
                         prior_by_kind.get(kind, 0)) for kind in kinds}


@dataclass(frozen=True)
class ProductMovementDelta:
    """One product's movement totals in both periods."""

    product_id: int = None
    product_name: str = ""
    sku: str = ""
    barcode: str = ""
    current: object = None
    prior: object = None
    movement_count: MetricDelta = None
    net_delta: MetricDelta = None
    by_kind: dict = field(default_factory=dict)

    @property
    def name(self): return self.product_name

    def as_dict(self):
        return {"product_id": self.product_id, "product_name": self.product_name,
                "sku": self.sku, "barcode": self.barcode,
                "movement_count": self.movement_count.as_dict(),
                "net_delta": self.net_delta.as_dict(),
                "by_kind": {k: d.as_dict() for k, d in self.by_kind.items()}}


@dataclass(frozen=True)
class PriorMovementSummary:
    """Movement summary comparison: current window vs prior."""

    start_date: object = None
    end_date: object = None
    prior_start_date: object = None
    prior_end_date: object = None
    salon_id: int = None
    current: object = None
    prior: object = None
    movement_count: MetricDelta = None
    net_delta: MetricDelta = None
    by_kind: dict = field(default_factory=dict)
    by_kind_counts: dict = field(default_factory=dict)
    by_product: list = field(default_factory=list)

    @property
    def total(self): return self.movement_count
    @property
    def days(self):
        return (self.end_date - self.start_date).days + 1 if self.start_date else 0
    length = days
    per_product = property(lambda self: self.by_product)  # noqa: E731

    def for_product(self, product):
        key = getattr(product, "pk", product)
        return next((r for r in self.by_product if r.product_id == key), None)

    def as_dict(self):
        iso = lambda d: d.isoformat() if d else None  # noqa: E731
        by = lambda d: {k: v.as_dict() for k, v in d.items()}  # noqa: E731
        return {"start_date": iso(self.start_date), "end_date": iso(self.end_date),
                "prior_start_date": iso(self.prior_start_date),
                "prior_end_date": iso(self.prior_end_date),
                "salon_id": self.salon_id,
                "movement_count": self.movement_count.as_dict(),
                "net_delta": self.net_delta.as_dict(),
                "by_kind": by(self.by_kind),
                "by_kind_counts": by(self.by_kind_counts),
                "by_product": [r.as_dict() for r in self.by_product]}

    __iter__ = lambda self: iter(self.by_product)  # noqa: E731
    __len__ = lambda self: len(self.by_product)  # noqa: E731

PriorMovementSummaryReport = PriorMovementSummary
_EMPTY_ROW = {"movement_count": 0, "net_delta": 0, "by_kind": {}}


def prior_movement_summary(start, end, salon=None):
    """Return the prior-period movement summary comparison.

    ``start`` / ``end`` are the current window's inclusive
    local-date bounds, exactly as in
    :func:`catalog.movement_summary.movement_summary` (called
    verbatim for both windows, so its ``ValueError``\ s —
    reversed range, missing or non-date bound — propagate).
    When ``salon`` is given, only that salon's movements count;
    otherwise every salon counts. Records nothing.
    """
    current = movement_summary(start, end, salon=salon)
    first, last = current.start_date, current.end_date
    length = (last - first).days + 1
    prior_end = first - timedelta(days=1)
    prior_start = first - timedelta(days=length)
    prior = movement_summary(prior_start, prior_end, salon=salon)
    cur_rows = {r["product_id"]: r for r in current.by_product}
    pri_rows = {r["product_id"]: r for r in prior.by_product}
    meta = {}
    for source in (current.by_product, prior.by_product):
        for row in source:
            meta[row["product_id"]] = row
    by_product = []
    for pid in sorted(meta, key=lambda p: (meta[p]["product_name"], p)):
        cur = cur_rows.get(pid, _EMPTY_ROW)
        pri = pri_rows.get(pid, _EMPTY_ROW)
        info = meta[pid]
        by_product.append(ProductMovementDelta(
            product_id=pid, product_name=info["product_name"], sku=info["sku"],
            barcode=info["barcode"],
            current=cur if pid in cur_rows else None,
            prior=pri if pid in pri_rows else None,
            movement_count=_delta("movement_count", cur["movement_count"],
                                  pri["movement_count"]),
            net_delta=_delta("net_delta", cur["net_delta"], pri["net_delta"]),
            by_kind=_kind_deltas("by_kind", cur["by_kind"], pri["by_kind"])))
    return PriorMovementSummary(
        start_date=first, end_date=last, prior_start_date=prior_start,
        prior_end_date=prior_end, salon_id=current.salon_id,
        current=current, prior=prior,
        movement_count=_delta("movement_count", current.movement_count,
                              prior.movement_count),
        net_delta=_delta("net_delta", current.net_delta, prior.net_delta),
        by_kind=_kind_deltas("by_kind", current.by_kind, prior.by_kind),
        by_kind_counts=_kind_deltas("by_kind_counts", current.by_kind_counts,
                                    prior.by_kind_counts),
        by_product=by_product)


#: Aliases, mirroring the naming convenience in sibling services.
prior_period_movement_summary = prior_movement_summary
compare_movement_summary = prior_movement_summary
get_prior_movement_summary = prior_movement_summary
