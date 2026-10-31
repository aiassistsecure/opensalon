"""Stock movement summary service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never creates, edits, or deletes a stock movement; the movement
ledger stays append-only and is only read here.

The ledger is the one source of truth: every figure here is
derived from ``StockMovement`` rows at call time and nothing is
stored, so a summary can never drift from the movements it
summarises. This complements :mod:`catalog.movement_export`,
which exports the individual rows; this module rolls the same
rows up into totals.

Public surface:

* :func:`movement_summary` — a :class:`MovementSummary` over an
  inclusive local-date range: totals by movement kind, totals by
  product, and the net quantity change per product.
* :func:`totals_by_kind` / :func:`totals_by_product` /
  :func:`net_change_by_product` — the individual rollups.

Fields per product row are exactly
:data:`PRODUCT_FIELDNAMES` — the same shape as the per-product
totals in :mod:`catalog.movement_export`: ``product_id``,
``product_name``, ``sku``, ``barcode``, ``movement_count``,
``net_delta`` (the sum of ``quantity_delta`` over the range), and
``by_kind`` (a dict of per-kind delta sums; only kinds present
for that product in the range appear). Only products with at
least one movement in the range appear. Negative sums are
reported as they stand, never clamped — the ledger is reported
as it is. Product rows are ordered by product name, then id.

Range semantics: ``start`` / ``end`` are required and may each be
a ``date`` or a ``datetime``. The range is inclusive at both
ends and covers whole local days: a ``date`` means that local
day, and a ``datetime`` is reduced to its local date (in the
current time zone), so a range always covers whole days. A
reversed range — ``end`` before ``start`` — raises
``ValueError``, as does a missing or non-date bound.

Salon scope is optional: when ``salon`` (a salon instance or its
id) is given, only movements for that salon's products count;
when it is ``None``, movements for every salon count.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from catalog.models import StockMovement

__all__ = [
    "PRODUCT_FIELDNAMES",
    "MovementSummary",
    "movement_summary",
    "stock_movement_summary",
    "summarize_movements",
    "totals_by_kind",
    "totals_by_product",
    "net_change_by_product",
]

#: Key order for each per-product totals dict (``by_kind`` holds
#: a nested dict and is therefore listed last). Same shape as
#: ``TOTAL_FIELDNAMES`` in :mod:`catalog.movement_export`.
PRODUCT_FIELDNAMES = [
    "product_id",
    "product_name",
    "sku",
    "barcode",
    "movement_count",
    "net_delta",
    "by_kind",
]

_KINDS = [kind for kind, _label in StockMovement.Kind.choices]


@dataclass(frozen=True)
class MovementSummary:
    """Movement totals over one inclusive local-date range.

    ``by_kind`` maps every movement kind to its net
    ``quantity_delta`` sum over the range (kinds with no
    movements read ``0``), and ``by_kind_counts`` maps every
    kind to its movement count. ``by_product`` is the list of
    per-product rows (see :data:`PRODUCT_FIELDNAMES`), and
    ``net_by_product`` maps product id to net quantity change.
    ``net_delta`` is the overall net change — the sum over the
    whole range — and ``movement_count`` the number of
    movements counted.
    """

    start_date: date = None
    end_date: date = None
    salon_id: int = None
    movement_count: int = 0
    net_delta: int = 0
    by_kind: dict = field(default_factory=dict)
    by_kind_counts: dict = field(default_factory=dict)
    by_product: list = field(default_factory=list)
    net_by_product: dict = field(default_factory=dict)

    @property
    def total(self):
        """Alias for ``movement_count``."""
        return self.movement_count

    @property
    def total_movements(self):
        """Alias for ``movement_count``."""
        return self.movement_count

    @property
    def net_change(self):
        """Alias for ``net_delta``."""
        return self.net_delta

    @property
    def totals_by_kind(self):
        """Alias for ``by_kind``."""
        return self.by_kind

    @property
    def totals_by_product(self):
        """Alias for ``by_product``."""
        return self.by_product

    def as_dict(self):
        """Return a plain, JSON-serializable dict of this summary."""
        return {
            "start_date": (
                self.start_date.isoformat() if self.start_date else None
            ),
            "end_date": (
                self.end_date.isoformat() if self.end_date else None
            ),
            "salon_id": self.salon_id,
            "movement_count": self.movement_count,
            "net_delta": self.net_delta,
            "by_kind": dict(self.by_kind),
            "by_kind_counts": dict(self.by_kind_counts),
            "by_product": [
                {**row, "by_kind": dict(row["by_kind"])}
                for row in self.by_product
            ],
            "net_by_product": {
                str(product_id): delta
                for product_id, delta in self.net_by_product.items()
            },
        }


def _as_local_date(value):
    """Reduce a ``date`` / ``datetime`` bound to its local date."""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    if isinstance(value, date):
        return value
    raise ValueError("range bounds must be a date or datetime")


def _resolve_range(start, end):
    """Return ``(first, last)`` local dates, or raise ValueError."""
    if start is None or end is None:
        raise ValueError("a start and an end date are required")
    first = _as_local_date(start)
    last = _as_local_date(end)
    if last < first:
        raise ValueError("range end must not be before range start")
    return first, last


def _movements_in_range(first, last, salon):
    tz = timezone.get_current_timezone()
    start_bound = datetime.combine(first, time.min, tzinfo=tz)
    end_bound = datetime.combine(
        last + timedelta(days=1), time.min, tzinfo=tz
    )
    queryset = (
        StockMovement.objects.filter(
            created_at__gte=start_bound, created_at__lt=end_bound
        )
        .select_related("product")
        .order_by("created_at", "id")
    )
    if salon is not None:
        queryset = queryset.filter(product__salon_id=getattr(salon, "pk", salon))
    return queryset


def movement_summary(start, end, salon=None):
    """Return a :class:`MovementSummary` for the range.

    ``start`` / ``end`` are inclusive local-date bounds (see the
    module docstring for range semantics); a reversed range
    raises ``ValueError``. When ``salon`` is given, only that
    salon's movements count; otherwise every salon counts. A
    range with no movements returns a zeroed summary — counts
    ``0``, every kind ``0``, no product rows — never ``None``.
    Records nothing.
    """
    first, last = _resolve_range(start, end)
    by_kind = {kind: 0 for kind in _KINDS}
    by_kind_counts = {kind: 0 for kind in _KINDS}
    products = {}
    movement_count = 0
    net_delta = 0
    for movement in _movements_in_range(first, last, salon):
        product = movement.product
        row = products.get(product.pk)
        if row is None:
            row = {
                "product_id": product.pk,
                "product_name": product.name,
                "sku": product.sku,
                "barcode": product.barcode,
                "movement_count": 0,
                "net_delta": 0,
                "by_kind": {},
            }
            products[product.pk] = row
        delta = int(movement.quantity_delta)
        kind = movement.kind
        movement_count += 1
        net_delta += delta
        by_kind[kind] = by_kind.get(kind, 0) + delta
        by_kind_counts[kind] = by_kind_counts.get(kind, 0) + 1
        row["movement_count"] += 1
        row["net_delta"] += delta
        row["by_kind"][kind] = row["by_kind"].get(kind, 0) + delta
    by_product = sorted(
        products.values(), key=lambda r: (r["product_name"], r["product_id"])
    )
    return MovementSummary(
        start_date=first,
        end_date=last,
        salon_id=getattr(salon, "pk", salon) if salon is not None else None,
        movement_count=movement_count,
        net_delta=net_delta,
        by_kind=by_kind,
        by_kind_counts=by_kind_counts,
        by_product=by_product,
        net_by_product={row["product_id"]: row["net_delta"] for row in by_product},
    )


def totals_by_kind(start, end, salon=None):
    """Return ``{kind: net_delta}`` over the range, zero-filled."""
    return movement_summary(start, end, salon=salon).by_kind


def totals_by_product(start, end, salon=None):
    """Return the per-product totals rows over the range."""
    return movement_summary(start, end, salon=salon).by_product


def net_change_by_product(start, end, salon=None):
    """Return ``{product_id: net_delta}`` over the range."""
    return movement_summary(start, end, salon=salon).net_by_product


#: Aliases, mirroring the naming convenience in sibling services.
stock_movement_summary = movement_summary
summarize_movements = movement_summary
