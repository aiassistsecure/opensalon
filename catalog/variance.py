"""Stocktake variance report service for the catalog.

Backend only — no views, templates, or UI.

A variance report is the read-only analysis of a physical count:
it compares what was counted against what the sheet expected,
without reconciling anything. Reconciling (recording STOCKTAKE
movements) lives in :mod:`catalog.stocktake`; this service never
writes — no ``StockMovement`` is created, updated, or deleted.

Input shape — the sheet service's shape: the expected side is a
sequence of :class:`catalog.stocktake_sheet.StocktakeSheetRow`
(as returned by ``stocktake_sheet(salon)``), and the counted side
is a mapping of counts keyed by product, product id, barcode/SKU
code, or the sheet row itself. For convenience ``salon`` may be
passed instead of sheet rows, in which case the sheet is built
via ``stocktake_sheet(salon)`` first. Pairs of
``(sheet_row, counted)`` are also accepted as a single argument.

Valuation follows :mod:`catalog.valuation` exactly: ``Product``
carries only its retail (selling) price, so a line's value impact
is ``difference * retail_price`` quantised to cents — retail value
impact, never cost, margin, or profit. Shortages contribute a
negative impact, overages a positive one, and the net total is
their sum; gross shortage / overage values are reported separately
(shortage value as the negative sum of shortage impacts).
"""
from dataclasses import dataclass
from decimal import Decimal

from catalog.models import Product
from catalog.stocktake_sheet import StocktakeSheetRow, stocktake_sheet

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class VarianceLine:
    """One product's stocktake variance.

    ``expected_stock`` is the sheet row's ``on_hand``,
    ``counted_stock`` the physical count, ``difference`` is
    ``counted_stock - expected_stock``, and ``retail_value_impact``
    is ``difference * unit_price`` (retail — see module docstring).
    ``name`` / ``sku`` / ``barcode`` are copied from the sheet row
    so a line is a self-contained record.
    """

    product: Product
    name: str
    sku: str
    barcode: str
    expected_stock: int
    counted_stock: int
    difference: int
    unit_price: Decimal
    retail_value_impact: Decimal

    @property
    def variance(self):
        """Alias for ``difference``."""
        return self.difference

    @property
    def expected(self):
        return self.expected_stock

    @property
    def on_hand(self):
        return self.expected_stock

    @property
    def counted(self):
        return self.counted_stock

    @property
    def retail_price(self):
        return self.unit_price

    @property
    def price(self):
        return self.unit_price

    @property
    def value_impact(self):
        """Alias for ``retail_value_impact``."""
        return self.retail_value_impact

    @property
    def line_value(self):
        return self.retail_value_impact

    @property
    def is_shortage(self):
        return self.difference < 0

    @property
    def is_overage(self):
        return self.difference > 0

    @property
    def is_match(self):
        return self.difference == 0


#: Descriptive alias.
StocktakeVarianceLine = VarianceLine


@dataclass(frozen=True)
class VarianceReport:
    """Stocktake variance report: per-product lines plus totals.

    Totals are sums over ``lines``: expected / counted / difference
    units, net retail value impact, gross shortage units and value
    (negative), and gross overage units and value (positive).
    Iterating / taking ``len()`` delegates to ``lines``.
    """

    lines: tuple
    total_expected: int
    total_counted: int
    total_difference: int
    total_retail_value_impact: Decimal
    total_shortage_units: int
    total_shortage_value: Decimal
    total_overage_units: int
    total_overage_value: Decimal

    def __iter__(self):
        return iter(self.lines)

    def __len__(self):
        return len(self.lines)

    @property
    def rows(self):
        """Alias for ``lines``."""
        return self.lines

    @property
    def variances(self):
        return self.lines

    @property
    def total_value_impact(self):
        return self.total_retail_value_impact

    @property
    def net_value_impact(self):
        return self.total_retail_value_impact

    @property
    def total_expected_stock(self):
        return self.total_expected

    @property
    def total_counted_stock(self):
        return self.total_counted

    @property
    def has_variance(self):
        return any(line.difference != 0 for line in self.lines)

    @property
    def shortage_count(self):
        return sum(1 for line in self.lines if line.difference < 0)

    @property
    def overage_count(self):
        return sum(1 for line in self.lines if line.difference > 0)

    @property
    def matched_count(self):
        return sum(1 for line in self.lines if line.difference == 0)

    @property
    def variance_count(self):
        return self.shortage_count + self.overage_count


#: Descriptive aliases.
StocktakeVarianceReport = VarianceReport
VarianceTotals = VarianceReport


def _clean_count(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("counted quantities must be non-negative integers")
    return value


def _resolve_key(row_by_pk, row_by_code, key):
    if isinstance(key, StocktakeSheetRow):
        row = row_by_pk.get(key.product.pk)
    elif isinstance(key, Product):
        row = row_by_pk.get(key.pk)
    elif isinstance(key, bool):
        row = None
    elif isinstance(key, int):
        row = row_by_pk.get(key)
    elif isinstance(key, str):
        row = row_by_code.get(key.strip())
    else:
        row = None
    if row is None:
        raise ValueError(f"count key does not match any sheet row: {key!r}")
    return row


def _normalise(sheet_rows, counts):
    """Return ordered ``[(sheet_row, counted), ...]`` or raise ValueError."""
    rows = list(sheet_rows)
    for row in rows:
        if not isinstance(row, StocktakeSheetRow):
            raise ValueError("sheet rows must be StocktakeSheetRow instances")
    row_by_pk = {}
    row_by_code = {}
    for row in rows:
        if row.product.pk in row_by_pk:
            raise ValueError(f"duplicate sheet row for product {row.product.pk}")
        row_by_pk[row.product.pk] = row
        for code in (row.barcode, row.sku):
            if code:
                row_by_code.setdefault(code, row)
    if counts is None:
        raise ValueError("counts must be a mapping of product to counted quantity")
    if hasattr(counts, "items"):
        items = list(counts.items())
    else:
        # Iterable of (key, counted) pairs.
        items = [(k, v) for k, v in counts]
    if not items:
        raise ValueError("counts must be a non-empty mapping of product to quantity")
    resolved = {}
    for key, value in items:
        counted = _clean_count(value)
        row = _resolve_key(row_by_pk, row_by_code, key)
        if row.product.pk in resolved:
            raise ValueError(f"duplicate count for product {row.product.pk}")
        resolved[row.product.pk] = counted
    # Preserve sheet order; uncounted sheet rows are not reported —
    # a variance needs both an expected and a counted quantity.
    return [(row, resolved[row.product.pk]) for row in rows
            if row.product.pk in resolved]


def stocktake_variance(sheet_or_salon, counts=None):
    """Return a :class:`VarianceReport` for a stocktake count.

    ``sheet_or_salon`` is either a sequence of
    ``StocktakeSheetRow`` (from ``stocktake_sheet``) or a salon,
    in which case its sheet is built first. ``counts`` maps a
    product / product id / barcode / SKU / sheet row to the counted
    quantity. Alternatively pass a single mapping or iterable of
    pairs keyed by sheet row. Read-only: records nothing.
    """
    if counts is None:
        # Single-argument form: counts keyed by sheet row, or pairs.
        if hasattr(sheet_or_salon, "items"):
            items = list(sheet_or_salon.items())
            if not items or not isinstance(items[0][0], StocktakeSheetRow):
                raise ValueError(
                    "single-argument form requires counts keyed by sheet row"
                )
            sheet_rows = [key for key, _ in items]
            counts_map = dict(items)
        else:
            pairs = list(sheet_or_salon)
            if not pairs:
                raise ValueError("counts must be non-empty")
            sheet_rows = [pair[0] for pair in pairs]
            counts_map = {pair[0]: pair[1] for pair in pairs}
        pairs = _normalise(sheet_rows, counts_map)
    elif isinstance(sheet_or_salon, (list, tuple)) or (
        sheet_or_salon and not hasattr(sheet_or_salon, "products")
        and not isinstance(sheet_or_salon, Product)
        and hasattr(sheet_or_salon, "__iter__")
    ):
        pairs = _normalise(list(sheet_or_salon), counts)
    else:
        # A salon (or salon-like object): build its sheet.
        pairs = _normalise(stocktake_sheet(sheet_or_salon), counts)

    lines = []
    total_expected = total_counted = total_difference = 0
    total_impact = ZERO
    shortage_units = overage_units = 0
    shortage_value = overage_value = ZERO
    for row, counted in pairs:
        difference = counted - row.on_hand
        impact = (row.retail_price * difference).quantize(ZERO)
        lines.append(VarianceLine(
            product=row.product, name=row.name, sku=row.sku,
            barcode=row.barcode, expected_stock=row.on_hand,
            counted_stock=counted, difference=difference,
            unit_price=row.retail_price, retail_value_impact=impact,
        ))
        total_expected += row.on_hand
        total_counted += counted
        total_difference += difference
        total_impact += impact
        if difference < 0:
            shortage_units += -difference
            shortage_value += impact
        elif difference > 0:
            overage_units += difference
            overage_value += impact
    return VarianceReport(
        lines=tuple(lines),
        total_expected=total_expected,
        total_counted=total_counted,
        total_difference=total_difference,
        total_retail_value_impact=total_impact.quantize(ZERO),
        total_shortage_units=shortage_units,
        total_shortage_value=shortage_value.quantize(ZERO),
        total_overage_units=overage_units,
        total_overage_value=overage_value.quantize(ZERO),
    )


#: Short / descriptive aliases.
variance_report = stocktake_variance
stocktake_variance_report = stocktake_variance
