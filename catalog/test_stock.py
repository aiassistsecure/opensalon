from decimal import Decimal

from django.core.exceptions import FieldDoesNotExist
from django.test import TestCase

from catalog.models import Product, StockMovement
from saloncore.models import Salon


class StockMovementTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.product = Product.objects.create(
            salon=self.salon,
            name="Shampoo",
            sku="SH-001",
            barcode="012345678905",
            price=Decimal("24.00"),
        )

    def move(self, kind, delta, **kwargs):
        return StockMovement.objects.create(
            product=self.product, kind=kind, quantity_delta=delta, **kwargs
        )

    def test_no_movements_means_zero_stock(self):
        self.assertEqual(self.product.current_stock, 0)

    def test_no_mutable_stock_counter_field(self):
        with self.assertRaises(FieldDoesNotExist):
            Product._meta.get_field("stock_quantity")

    def test_receive_adds_stock(self):
        self.move(StockMovement.Kind.RECEIVE, 10)
        self.assertEqual(self.product.current_stock, 10)

    def test_sale_subtracts_stock(self):
        self.move(StockMovement.Kind.RECEIVE, 10)
        self.move(StockMovement.Kind.SALE, -3)
        self.assertEqual(self.product.current_stock, 7)

    def test_adjustment_works_in_both_directions(self):
        self.move(StockMovement.Kind.RECEIVE, 10)
        self.move(StockMovement.Kind.ADJUSTMENT, -2)
        self.assertEqual(self.product.current_stock, 8)
        self.move(StockMovement.Kind.ADJUSTMENT, 5)
        self.assertEqual(self.product.current_stock, 13)

    def test_stocktake_records_delta_not_absolute_count(self):
        self.move(StockMovement.Kind.RECEIVE, 10)
        self.move(StockMovement.Kind.SALE, -2)
        # Counted 6 on the shelf vs 8 derived: stocktake delta is -2.
        self.move(StockMovement.Kind.STOCKTAKE, -2)
        self.assertEqual(self.product.current_stock, 6)

    def test_combined_math_across_kinds(self):
        self.move(StockMovement.Kind.RECEIVE, 20)
        self.move(StockMovement.Kind.SALE, -4)
        self.move(StockMovement.Kind.SALE, -1)
        self.move(StockMovement.Kind.ADJUSTMENT, -1)
        self.move(StockMovement.Kind.RECEIVE, 6)
        self.assertEqual(self.product.current_stock, 20)

    def test_movements_are_per_product(self):
        other = Product.objects.create(
            salon=self.salon, name="Conditioner", price=Decimal("26.00")
        )
        self.move(StockMovement.Kind.RECEIVE, 10)
        StockMovement.objects.create(
            product=other, kind=StockMovement.Kind.RECEIVE, quantity_delta=3
        )
        self.assertEqual(self.product.current_stock, 10)
        self.assertEqual(other.current_stock, 3)

    def test_kind_choices_note_default_and_created_at(self):
        movement = self.move(StockMovement.Kind.RECEIVE, 10)
        self.assertEqual(movement.note, "")
        self.assertIsNotNone(movement.created_at)
        self.assertIn(movement, list(self.product.stock_movements.all()))
        self.assertEqual(
            {value for value, _ in StockMovement.Kind.choices},
            {"receive", "sale", "adjustment", "stocktake"},
        )

    def test_note_is_optional_and_stored(self):
        movement = self.move(
            StockMovement.Kind.ADJUSTMENT, -1, note="Damaged bottle"
        )
        self.assertEqual(movement.note, "Damaged bottle")


class ProductLookupTests(TestCase):
    def setUp(self):
        salon = Salon.objects.create(name="Example Salon")
        self.product = Product.objects.create(
            salon=salon,
            name="Shampoo",
            sku="SH-001",
            barcode="012345678905",
            price=Decimal("24.00"),
        )

    def test_lookup_by_barcode(self):
        self.assertEqual(Product.lookup_by_barcode("012345678905"), self.product)

    def test_lookup_by_barcode_unknown_and_blank(self):
        self.assertIsNone(Product.lookup_by_barcode("999999999999"))
        self.assertIsNone(Product.lookup_by_barcode(""))
        self.assertIsNone(Product.lookup_by_barcode(None))

    def test_lookup_by_sku(self):
        self.assertEqual(Product.lookup_by_sku("SH-001"), self.product)
        self.assertIsNone(Product.lookup_by_sku("NOPE"))
        self.assertIsNone(Product.lookup_by_sku(""))

    def test_lookup_by_scan_matches_barcode_or_sku(self):
        self.assertEqual(Product.lookup_by_scan("012345678905"), self.product)
        self.assertEqual(Product.lookup_by_scan("SH-001"), self.product)
        self.assertIsNone(Product.lookup_by_scan("unknown"))
