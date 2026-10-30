"""Barcode scan service for stock receiving and selling.

Backend only — no views, templates, or UI. Built for standard
keyboard-wedge USB/Bluetooth scanners: a scanner delivers one code
string (barcode or SKU) exactly as if typed, and this module turns
that code into a ``StockMovement``. No proprietary hardware, scanner
SDK, or device protocol is assumed.

Stock stays derived from movements only: scanning never writes a
stock counter — it appends a movement (``Product.current_stock``
sums the deltas), so the movement log remains the one source of
truth.

Unknown or blank codes never raise: they return a clean not-found
``ScanResult`` so a mis-scan at the till cannot crash checkout.
Selling below zero is allowed (salons sell-then-reconcile) — the
movement is recorded and the result flags the negative stock.
"""
from dataclasses import dataclass

from catalog.models import Product, StockMovement


@dataclass(frozen=True)
class ScanResult:
    """Outcome of one scan.

    On success ``found`` is True and ``product``, ``movement`` and
    ``current_stock`` (the derived stock *after* the movement) are
    set. On a miss every payload field is None and ``movement`` is
    None — no movement was recorded. ``below_zero`` is True only
    when a sale left the derived stock negative.
    """

    found: bool
    product: Product | None = None
    movement: StockMovement | None = None
    current_stock: int | None = None
    below_zero: bool = False

    @property
    def new_current_stock(self):
        """Alias for ``current_stock`` (stock after the movement)."""
        return self.current_stock

    @property
    def went_negative(self):
        """Alias for ``below_zero``."""
        return self.below_zero


def _resolve(salon, code):
    """Resolve ``code`` to a product of ``salon``, or None.

    Reuses ``Product.lookup_by_scan`` (barcode first, SKU fallback)
    and guards it by salon: the model lookups are global, so a code
    belonging to another salon must not move that salon's stock.
    When the global first match is another salon's product, a
    salon-scoped lookup still finds this salon's own product if it
    carries the same code.
    """
    if code is None:
        return None
    code = str(code).strip()
    if not code:
        return None
    product = Product.lookup_by_scan(code)
    salon_id = getattr(salon, "pk", salon)
    if product is not None and (salon is None or product.salon_id == salon_id):
        return product
    if salon is None:
        return product
    return (
        Product.objects.filter(salon=salon, barcode=code).first()
        or Product.objects.filter(salon=salon, sku=code).first()
    )


def _scan(salon, code, quantity, kind, sign):
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValueError("quantity must be a positive integer")
    product = _resolve(salon, code)
    if product is None:
        return ScanResult(found=False)
    movement = StockMovement.objects.create(
        product=product,
        kind=kind,
        quantity_delta=sign * quantity,
        note=f"Barcode scan ({kind})",
    )
    current = product.current_stock
    return ScanResult(
        found=True,
        product=product,
        movement=movement,
        current_stock=current,
        below_zero=current < 0,
    )


def scan_receive(salon, code, quantity=1):
    """Record receiving ``quantity`` units of the scanned product.

    Appends a RECEIVE movement with a positive delta and returns a
    ``ScanResult`` with the new derived stock. Unknown/blank codes
    return ``ScanResult(found=False)`` and record nothing.
    """
    return _scan(salon, code, quantity, StockMovement.Kind.RECEIVE, +1)


def scan_sell(salon, code, quantity=1):
    """Record selling ``quantity`` units of the scanned product.

    Appends a SALE movement with a negative delta and returns a
    ``ScanResult`` with the new derived stock. Stock may go
    negative (sell-then-reconcile); when it does, the result's
    ``below_zero`` flag is True. Unknown/blank codes return
    ``ScanResult(found=False)`` and record nothing.
    """
    return _scan(salon, code, quantity, StockMovement.Kind.SALE, -1)
