import io
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.adjust import adjust_stock
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class AdjustStockCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("24.00"))
        StockMovement.objects.create(
            product=self.product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=10)

    def adjustments(self):
        return StockMovement.objects.filter(
            product=self.product, kind=StockMovement.Kind.ADJUSTMENT)

    def test_happy_path_records_one_adjustment_matching_service(self):
        out = io.StringIO()
        call_command("adjust_stock", salon_id=self.salon.pk,
                     product_id=self.product.pk, delta=-3,
                     reason="Damaged bottles", stdout=out)
        (movement,) = self.adjustments()
        self.assertEqual(movement.quantity_delta, -3)
        self.assertEqual(movement.note, "Damaged bottles")
        self.assertEqual(self.product.current_stock, 7)
        text = out.getvalue()
        self.assertIn("Shampoo", text)
        self.assertIn("-3", text)
        self.assertIn("Damaged bottles", text)
        self.assertIn("current stock 7", text)
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_positive_adjustment_via_flag_form(self):
        out = io.StringIO()
        call_command("adjust_stock", "--salon-id", str(self.salon.pk),
                     "--product-id", str(self.product.pk),
                     "--delta", "5", "--reason", "Found a case",
                     stdout=out)
        self.assertEqual(self.product.current_stock, 15)
        self.assertIn("current stock 15", out.getvalue())

    def test_result_matches_direct_service_call(self):
        expected = adjust_stock(self.product, 2, "Opening count fix")
        out = io.StringIO()
        call_command("adjust_stock", salon_id=self.salon.pk,
                     product_id=self.product.pk, delta=2,
                     reason="Opening count fix", stdout=out)
        self.assertEqual(self.product.current_stock, expected + 2)
        self.assertIn(f"current stock {expected + 2}",
                      out.getvalue())

    def test_dry_run_writes_nothing_and_previews_movement(self):
        before = StockMovement.objects.count()
        out = io.StringIO()
        call_command("adjust_stock", salon_id=self.salon.pk,
                     product_id=self.product.pk, delta=-4,
                     reason="Broken in transit", dry_run=True,
                     stdout=out)
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(self.adjustments().count(), 0)
        self.assertEqual(self.product.current_stock, 10)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn("adjustment", text)
        self.assertIn("-4", text)
        self.assertIn("Shampoo", text)
        self.assertIn(f"product {self.product.pk}", text)
        self.assertIn("Broken in transit", text)
        self.assertIn("resulting stock 6", text)

    def test_dry_run_flag_form_positive_delta(self):
        out = io.StringIO()
        call_command("adjust_stock", "--salon-id", str(self.salon.pk),
                     "--product-id", str(self.product.pk),
                     "--delta", "5", "--reason", "Found a case",
                     "--dry-run", stdout=out)
        self.assertEqual(self.adjustments().count(), 0)
        self.assertIn("resulting stock 15", out.getvalue())

    def test_dry_run_below_zero_raises_and_writes_nothing(self):
        before = StockMovement.objects.count()
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=self.salon.pk,
                         product_id=self.product.pk, delta=-11,
                         reason="Write-off", dry_run=True,
                         stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(self.product.current_stock, 10)

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=999999,
                         product_id=self.product.pk, delta=1,
                         reason="Fix", stdout=io.StringIO())
        self.assertEqual(self.adjustments().count(), 0)

    def test_unknown_product_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=self.salon.pk,
                         product_id=999999, delta=1, reason="Fix",
                         stdout=io.StringIO())
        self.assertEqual(self.adjustments().count(), 0)

    def test_product_of_another_salon_raises_command_error(self):
        other = Salon.objects.create(name="Other Salon")
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=other.pk,
                         product_id=self.product.pk, delta=1,
                         reason="Fix", stdout=io.StringIO())
        self.assertEqual(self.adjustments().count(), 0)
        self.assertEqual(self.product.current_stock, 10)

    def test_below_zero_raises_command_error_and_records_nothing(self):
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=self.salon.pk,
                         product_id=self.product.pk, delta=-11,
                         reason="Write-off", stdout=io.StringIO())
        self.assertEqual(self.adjustments().count(), 0)
        self.assertEqual(self.product.current_stock, 10)

    def test_zero_delta_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=self.salon.pk,
                         product_id=self.product.pk, delta=0,
                         reason="No-op", stdout=io.StringIO())
        self.assertEqual(self.adjustments().count(), 0)

    def test_blank_reason_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=self.salon.pk,
                         product_id=self.product.pk, delta=1,
                         reason="   ", stdout=io.StringIO())
        self.assertEqual(self.adjustments().count(), 0)
