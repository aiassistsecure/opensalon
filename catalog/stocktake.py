"""Stocktake / reconcile service for the catalog.

Backend only — no views, templates, or UI, and no proprietary
scanner protocol: counted quantities arrive as plain data, however
they were collected (e.g. tallied from standard keyboard-wedge
barcode scans via :mod:`catalog.scanning`).

A stocktake compares a physical count against the stock derived
from ``StockMovement`` rows (``Product.current_stock`` — movements
remain the one source of truth; no stock counter is ever written).
For every product whose count differs from the derived stock, one
reconciling ``StockMovement`` of kind ``STOCKTAKE`` is recorded
with ``quantity_delta = counted - derived``, so after the call the
derived stock equals the count. Products that match get no
movement.

Idempotency: each stocktake carries a caller-supplied ``reference``
(stored verbatim in the reconciling movements' ``note`` as
``"Stocktake <reference>"``). Re-running with a reference that has
already produced reconciling movements records nothing new and
returns ``already_applied=True`` with the variances reconstructed
from the original movements. A reference is the unit of
idempotency: use a fresh reference for a fresh count. (A count in
which nothing varied produces no movements and is therefore
trivially idempotent.)
"""
from dataclasses import dataclass

from django.db import transaction

from catalog.models import Product, StockMovement
from catalog.scanning import _resolve

NOTE_PREFIX = "Stocktake "


@dataclass(frozen=True)
class Variance:
    """One product's count versus its derived stock.

    ``variance`` is ``counted_stock - expected_stock`` and is the
    ``quantity_delta`` of the reconciling movement, when one was
    (or would be) recorded. ``movement`` is None for a dry run, for
    a zero variance, and is the recorded movement otherwise.
    """

    product: Product
    expected_stock: int
    counted_stock: int
    variance: int
    movement: StockMovement | None = None

    @property
    def derived_stock(self):
        """Alias for ``expected_stock``."""
        return self.expected_stock

    @property
    def difference(self):
        """Alias for ``variance``."""
        return self.variance


@dataclass(frozen=True)
class StocktakeResult:
    """Outcome of :func:`reconcile_stocktake`."""

    reference: str
    variances: tuple
    already_applied: bool = False

    @property
    def movements(self):
        """The reconciling movements recorded (or originally recorded)."""
        return tuple(v.movement for v in self.variances if v.movement is not None)

    @property
    def has_variance(self):
        return any(v.variance != 0 for v in self.variances)


def _note(reference):
    return f"{NOTE_PREFIX}{reference}"


def _clean_reference(reference):
    ref = str(reference or "").strip()
    if not ref:
        raise ValueError("a non-blank stocktake reference is required")
    if len(_note(ref)) > 255:
        raise ValueError("stocktake reference is too long")
    return ref


def _clean_count(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("counted quantities must be non-negative integers")
    return value


def _resolve_counts(salon, counts):
    """Normalise ``counts`` to an ordered ``{Product: counted}`` dict.

    Keys may be ``Product`` instances, integer product ids, or
    barcode/SKU code strings (resolved within ``salon``). Unknown
    keys, products of another salon, and two keys resolving to the
    same product all raise ``ValueError`` — silently skipping a
    counted product would corrupt the reconciliation.
    """
    if not counts or not hasattr(counts, "items"):
        raise ValueError("counts must be a non-empty mapping of product to quantity")
    salon_id = getattr(salon, "pk", salon)
    resolved = {}
    for key, value in counts.items():
        counted = _clean_count(value)
        if isinstance(key, Product):
            product = key
            if salon is not None and product.salon_id != salon_id:
                raise ValueError(f"product {product.pk} does not belong to this salon")
        elif isinstance(key, int) and not isinstance(key, bool):
            product = Product.objects.filter(pk=key, salon_id=salon_id).first()
            if product is None:
                raise ValueError(f"unknown product id: {key}")
        elif isinstance(key, str):
            product = _resolve(salon, key)
            if product is None:
                raise ValueError(f"unknown barcode/SKU code: {key!r}")
        else:
            raise ValueError(f"unsupported count key: {key!r}")
        if product.pk in resolved:
            raise ValueError(f"duplicate count for product {product.pk}")
        resolved[product.pk] = (product, counted)
    return [resolved[pk] for pk in sorted(resolved)]


def compute_variances(salon, counts):
    """Dry run: return the variance list, recording nothing."""
    return [
        Variance(
            product=product,
            expected_stock=product.current_stock,
            counted_stock=counted,
            variance=counted - product.current_stock,
        )
        for product, counted in _resolve_counts(salon, counts)
    ]


def reconcile_stocktake(salon, counts, reference):
    """Reconcile derived stock to ``counts`` under ``reference``.

    Records one STOCKTAKE movement per varying product (delta =
    counted - derived) and returns a ``StocktakeResult`` whose
    variances carry those movements. Idempotent per reference —
    see the module docstring.
    """
    ref = _clean_reference(reference)
    pairs = _resolve_counts(salon, counts)
    existing = {
        m.product_id: m
        for m in StockMovement.objects.filter(
            product__in=[p for p, _ in pairs],
            kind=StockMovement.Kind.STOCKTAKE,
            note=_note(ref),
        )
    }
    if existing:
        variances = []
        for product, counted in pairs:
            movement = existing.get(product.pk)
            if movement is None:
                expected = product.current_stock
                variances.append(Variance(product, expected, counted, counted - expected))
            else:
                variances.append(
                    Variance(
                        product=product,
                        expected_stock=counted - movement.quantity_delta,
                        counted_stock=counted,
                        variance=movement.quantity_delta,
                        movement=movement,
                    )
                )
        return StocktakeResult(reference=ref, variances=tuple(variances), already_applied=True)

    variances = []
    with transaction.atomic():
        for product, counted in pairs:
            expected = product.current_stock
            delta = counted - expected
            movement = None
            if delta != 0:
                movement = StockMovement.objects.create(
                    product=product,
                    kind=StockMovement.Kind.STOCKTAKE,
                    quantity_delta=delta,
                    note=_note(ref),
                )
            variances.append(Variance(product, expected, counted, delta, movement))
    return StocktakeResult(reference=ref, variances=tuple(variances))
