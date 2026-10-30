from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.scanning import ScanResult, scan_receive, scan_sell
from saloncore.models import Salon


class ScanServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.product = Product.objects.create(
            salon=self.salon,
            name="Shampoo",
            sku="SH-001",
            barcode="012345678905",
            price=Decimal("24.00"),
        )

    def test_receive_by_barcode_records_positive_movement(self):
        result = scan_receive(self.salon, "012345678905", quantity=10)
        self.assertIsInstance(result, ScanResult)
        self.assertTrue(result.found)
        self.assertEqual(result.product, self.product)
        self.assertEqual(result.movement.kind, StockMovement.Kind.RECEIVE)
        self.assertEqual(result.movement.quantity_delta, 10)
        self.assertEqual(result.current_stock, 10)
        self.assertEqual(result.new_current_stock, 10)
        self.assertFalse(result.below_zero)
        self.assertEqual(self.product.current_stock, 10)

    def test_receive_defaults_to_one_and_resolves_sku(self):
        result = scan_receive(self.salon, "SH-001")
        self.assertTrue(result.found)
        self.assertEqual(result.movement.quantity_delta, 1)
        self.assertEqual(result.current_stock, 1)

    def test_receive_trims_whitespace_from_scanned_code(self):
        result = scan_receive(self.salon, "  012345678905\n", quantity=2)
        self.assertTrue(result.found)
        self.assertEqual(result.current_stock, 2)

    def test_sell_by_barcode_records_negative_movement(self):
        scan_receive(self.salon, "012345678905", quantity=10)
        result = scan_sell(self.salon, "012345678905", quantity=3)
        self.assertTrue(result.found)
        self.assertEqual(result.movement.kind, StockMovement.Kind.SALE)
        self.assertEqual(result.movement.quantity_delta, -3)
        self.assertEqual(result.current_stock, 7)
        self.assertFalse(result.below_zero)

    def test_sell_defaults_to_one(self):
        scan_receive(self.salon, "SH-001", quantity=2)
        result = scan_sell(self.salon, "SH-001")
        self.assertEqual(result.movement.quantity_delta, -1)
        self.assertEqual(result.current_stock, 1)

    def test_sell_to_exactly_zero_is_not_flagged(self):
        scan_receive(self.salon, "012345678905", quantity=2)
        result = scan_sell(self.salon, "012345678905", quantity=2)
        self.assertEqual(result.current_stock, 0)
        self.assertFalse(result.below_zero)
        self.assertFalse(result.went_negative)

    def test_sell_below_zero_is_allowed_and_flagged(self):
        scan_receive(self.salon, "012345678905", quantity=1)
        result = scan_sell(self.salon, "012345678905", quantity=3)
        self.assertTrue(result.found)
        self.assertEqual(result.movement.quantity_delta, -3)
        self.assertEqual(result.current_stock, -2)
        self.assertTrue(result.below_zero)
        self.assertTrue(result.went_negative)
        self.assertEqual(self.product.current_stock, -2)

    def test_unknown_code_returns_not_found_and_records_nothing(self):
        for func in (scan_receive, scan_sell):
            result = func(self.salon, "999999999999")
            self.assertFalse(result.found)
            self.assertIsNone(result.product)
            self.assertIsNone(result.movement)
            self.assertIsNone(result.current_stock)
            self.assertFalse(result.below_zero)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_blank_codes_return_not_found_and_never_raise(self):
        for code in ("", "   ", None):
            self.assertFalse(scan_receive(self.salon, code).found)
            self.assertFalse(scan_sell(self.salon, code).found)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_code_from_another_salon_is_not_found(self):
        other = Salon.objects.create(name="Other Salon")
        result = scan_receive(other, "012345678905", quantity=5)
        self.assertFalse(result.found)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(self.product.current_stock, 0)

    def test_same_code_in_two_salons_resolves_to_callers_salon(self):
        other = Salon.objects.create(name="Other Salon")
        own = Product.objects.create(
            salon=other, name="Other Shampoo", barcode="012345678905",
            price=Decimal("20.00"),
        )
        result = scan_receive(other, "012345678905", quantity=4)
        self.assertTrue(result.found)
        self.assertEqual(result.product, own)
        self.assertEqual(own.current_stock, 4)
        self.assertEqual(self.product.current_stock, 0)

    def test_stock_stays_derived_from_scan_movements(self):
        scan_receive(self.salon, "012345678905", quantity=5)
        scan_sell(self.salon, "012345678905", quantity=2)
        scan_receive(self.salon, "SH-001", quantity=1)
        self.assertEqual(self.product.stock_movements.count(), 3)
        self.assertEqual(self.product.current_stock, 4)

    def test_non_positive_quantity_raises_and_records_nothing(self):
        for func in (scan_receive, scan_sell):
            with self.assertRaises(ValueError):
                func(self.salon, "012345678905", quantity=0)
            with self.assertRaises(ValueError):
                func(self.salon, "012345678905", quantity=-2)
        self.assertEqual(StockMovement.objects.count(), 0)
