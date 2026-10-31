"""Stock movement history service for the catalog.

Backend only — no views, templates, or UI. Read-only: this service
never records, edits, or deletes a movement.

The history of one product is its ``StockMovement`` ledger read
back chronologically (``created_at``, then ``id`` — the model's
own ordering, so movements created in the same instant keep their
recording order). Each entry carries a ``running_balance``: the
cumulative sum of ``quantity_delta`` up to and including that
movement. The final entry's running balance therefore equals
``Product.current_stock`` — stock is derived, never stored, and
the movement log stays the one source of truth. A product with no
movements has an empty history and a final balance of 0; balances
are reported as the ledger stands, never clamped (a sale recorded
before its receipt legitimately passes through negative).

Salon scoping: the product is resolved *within* the given salon.
A product belonging to another salon raises ``ValueError`` rather
than leaking its history across salons.
"""
from dataclasses import dataclass
from datetime import datetime

from catalog.models import Product, StockMovement


@dataclass(frozen=True)
class HistoryEntry:
    """One movement in a product's history.

    ``kind``, ``quantity_delta``, ``note``, and ``created_at`` are
    copied from the movement so an entry is self-contained;
    ``movement`` keeps the ledger row itself. ``running_balance``
    is the derived stock immediately after this movement landed.
    """

    movement: StockMovement
    kind: str
    quantity_delta: int
    note: str
    created_at: datetime
    running_balance: int

    @property
    def balance(self):
        """Alias for ``running_balance``."""
        return self.running_balance

    @property
    def balance_after(self):
        """Alias for ``running_balance``."""
        return self.running_balance

    @property
    def delta(self):
        """Alias for ``quantity_delta``."""
        return self.quantity_delta


@dataclass(frozen=True)
class StockHistory:
    """One product's full movement history.

    ``entries`` is a tuple of :class:`HistoryEntry` in
    chronological order; ``final_balance`` is the last entry's
    running balance (0 when there are no entries) and equals the
    product's movement-derived current stock. Iterating / taking
    ``len()`` delegates to ``entries``.
    """

    product: Product
    salon_id: int
    entries: tuple
    final_balance: int

    def __iter__(self):
        return iter(self.entries)

    def __len__(self):
        return len(self.entries)

    @property
    def movement_count(self):
        """Number of movements in the history."""
        return len(self.entries)

    @property
    def current_stock(self):
        """Alias for ``final_balance``."""
        return self.final_balance

    @property
    def on_hand(self):
        """Alias for ``final_balance``."""
        return self.final_balance


def _resolve_product(salon, product):
    salon_id = getattr(salon, "pk", salon)
    if isinstance(product, Product):
        if product.pk is None:
            raise ValueError("product must be a saved Product instance")
        if product.salon_id != salon_id:
            raise ValueError(f"product {product.pk} does not belong to this salon")
        return product
    if isinstance(product, int) and not isinstance(product, bool):
        found = Product.objects.filter(pk=product, salon_id=salon_id).first()
        if found is None:
            raise ValueError(f"unknown product id for this salon: {product}")
        return found
    raise ValueError("product must be a saved Product instance or product id")


def stock_history(salon, product=None):
    """Return the stock movement history for one product of ``salon``.

    ``product`` may be a saved :class:`~catalog.models.Product` or
    its integer id (resolved within ``salon``). As a convenience,
    ``stock_history(product)`` with a single Product argument uses
    that product's own salon.

    Returns a :class:`StockHistory` whose entries are chronological
    (``created_at``, then ``id``) and each carry the running
    balance derived from the ledger. Raises ``ValueError`` when the
    product is unsaved, unknown, belongs to another salon, or is
    neither a Product nor an id. Records nothing.
    """
    if product is None and isinstance(salon, Product):
        product, salon = salon, salon.salon
    if product is None:
        raise ValueError("a product is required")
    product = _resolve_product(salon, product)
    entries = []
    balance = 0
    movements = (
        StockMovement.objects.filter(product=product, product__salon_id=product.salon_id)
        .order_by("created_at", "id")
    )
    for movement in movements:
        balance += movement.quantity_delta
        entries.append(
            HistoryEntry(
                movement=movement,
                kind=movement.kind,
                quantity_delta=movement.quantity_delta,
                note=movement.note,
                created_at=movement.created_at,
                running_balance=balance,
            )
        )
    return StockHistory(
        product=product,
        salon_id=product.salon_id,
        entries=tuple(entries),
        final_balance=balance,
    )


#: Short alias, mirroring the naming convenience in sibling services.
product_history = stock_history
history = stock_history
