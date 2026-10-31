from decimal import Decimal

from django.test import TestCase

from catalog.adjust import adjust_stock
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class AdjustStockTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.product = Product.objects.create(
            salon=self.salon,
            name="Shampoo",
            sku="SH-001",
            barcode="012345678905",
            price=Decimal("24.00"),
        )

    def seed(self, delta, kind=StockMovement.Kind.RECEIVE):
        return StockMovement.objects.create(
            product=self.product, kind=kind, quantity_delta=delta
        )

    def adjustments(self):
        return StockMovement.objects.filter(
            product=self.product, kind=StockMovement.Kind.ADJUSTMENT
        )

    # --- happy paths ---------------------------------------------
    def test_positive_adjustment_creates_movement_and_returns_new_stock(self):
        self.seed(10)
        result = adjust_stock(self.product, 5, "Found a case in storage")
        self.assertEqual(result, 15)
        self.assertEqual(result, self.product.current_stock)
        (movement,) = self.adjustments()
        self.assertEqual(movement.quantity_delta, 5)
        self.assertEqual(movement.note, "Found a case in storage")

    def test_negative_adjustment_within_stock(self):
        self.seed(10)
        result = adjust_stock(self.product, -3, "Damaged bottles")
        self.assertEqual(result, 7)
        (movement,) = self.adjustments()
        self.assertEqual(movement.quantity_delta, -3)
        self.assertEqual(movement.note, "Damaged bottles")

    def test_adjustment_down_to_exactly_zero_is_allowed(self):
        self.seed(4)
        self.assertEqual(adjust_stock(self.product, -4, "Write-off"), 0)
        self.assertEqual(self.product.current_stock, 0)

    def test_adjustment_on_empty_stock_positive(self):
        self.assertEqual(adjust_stock(self.product, 2, "Opening count fix"), 2)

    def test_return_is_derived_from_full_ledger(self):
        self.seed(20)
        self.seed(-4, kind=StockMovement.Kind.SALE)
        self.seed(-1, kind=StockMovement.Kind.ADJUSTMENT)
        # Derived before this call: 15; +6 -> 21.
        self.assertEqual(adjust_stock(self.product, 6, "Recount"), 21)
        self.assertEqual(self.product.current_stock, 21)

    def test_reason_is_stripped_and_stored(self):
        adjust_stock(self.product, 1, "  Recount  ")
        (movement,) = self.adjustments()
        self.assertEqual(movement.note, "Recount")

    def test_adjustment_is_per_product(self):
        other = Product.objects.create(
            salon=self.salon, name="Conditioner", price=Decimal("26.00")
        )
        adjust_stock(self.product, 3, "Recount")
        self.assertEqual(other.current_stock, 0)
        self.assertEqual(StockMovement.objects.filter(product=other).count(), 0)

    # --- negative-stock rejection --------------------------------
    def test_adjustment_below_zero_is_rejected_and_records_nothing(self):
        self.seed(3)
        before = StockMovement.objects.count()
        with self.assertRaises(ValueError):
            adjust_stock(self.product, -4, "Damaged")
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(self.product.current_stock, 3)

    def test_negative_adjustment_on_empty_stock_is_rejected(self):
        with self.assertRaises(ValueError):
            adjust_stock(self.product, -1, "Damaged")
        self.assertEqual(self.adjustments().count(), 0)

    # --- validation ----------------------------------------------
    def test_zero_delta_is_rejected(self):
        with self.assertRaises(ValueError):
            adjust_stock(self.product, 0, "No-op")
        self.assertEqual(self.adjustments().count(), 0)

    def test_non_integer_delta_is_rejected(self):
        for bad in (True, 1.5, "2", None):
            with self.assertRaises(ValueError):
                adjust_stock(self.product, bad, "Recount")
        self.assertEqual(self.adjustments().count(), 0)

    def test_blank_reason_is_rejected(self):
        for bad in ("", "   ", None):
            with self.assertRaises(ValueError):
                adjust_stock(self.product, 1, bad)
        self.assertEqual(self.adjustments().count(), 0)

    def test_overlong_reason_is_rejected(self):
        with self.assertRaises(ValueError):
            adjust_stock(self.product, 1, "x" * 256)
        self.assertEqual(self.adjustments().count(), 0)

    def test_unsaved_or_missing_product_is_rejected(self):
        unsaved = Product(
            salon=self.salon, name="Ghost", price=Decimal("1.00")
        )
        for bad in (None, unsaved, "SH-001"):
            with self.assertRaises(ValueError):
                adjust_stock(bad, 1, "Recount")
        self.assertEqual(self.adjustments().count(), 0)
