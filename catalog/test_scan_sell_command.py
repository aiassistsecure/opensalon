import io
import json
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.scanning import scan_receive
from saloncore.models import Salon


class ScanSellCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("24.00"))
        scan_receive(self.salon, "012345678905", quantity=10)

    def test_happy_path_by_barcode(self):
        out = io.StringIO()
        call_command("scan_sell", salon_id=self.salon.pk,
                     code="012345678905", quantity=3, stdout=out)
        movement = StockMovement.objects.order_by("id").last()
        self.assertEqual(movement.kind, StockMovement.Kind.SALE)
        self.assertEqual(movement.quantity_delta, -3)
        self.assertEqual(self.product.current_stock, 7)
        text = out.getvalue()
        self.assertIn("Shampoo", text)
        self.assertIn("current stock 7", text)
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_happy_path_by_sku_defaults_to_one(self):
        out = io.StringIO()
        call_command("scan_sell", salon_id=self.salon.pk,
                     code="SH-001", stdout=out)
        self.assertEqual(self.product.current_stock, 9)
        self.assertIn("current stock 9", out.getvalue())

    def test_sell_below_zero_is_allowed_and_flagged_in_summary(self):
        out = io.StringIO()
        call_command("scan_sell", salon_id=self.salon.pk,
                     code="012345678905", quantity=12, stdout=out)
        self.assertEqual(self.product.current_stock, -2)
        self.assertIn("below zero", out.getvalue())

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("scan_sell", salon_id=999999,
                         code="012345678905", stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_unknown_code_raises_command_error_and_records_nothing(self):
        with self.assertRaises(CommandError):
            call_command("scan_sell", salon_id=self.salon.pk,
                         code="999999999999", stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_non_positive_quantity_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("scan_sell", salon_id=self.salon.pk,
                         code="012345678905", quantity=0,
                         stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_dry_run_writes_nothing_and_previews_movement(self):
        out = io.StringIO()
        call_command("scan_sell", salon_id=self.salon.pk,
                     code="012345678905", quantity=3, dry_run=True,
                     stdout=out)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(self.product.current_stock, 10)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn("sale", text)
        self.assertIn("-3", text)
        self.assertIn("Shampoo", text)
        self.assertIn(f"product {self.product.pk}", text)
        self.assertIn("resulting stock 7", text)

    def test_dry_run_below_zero_previews_without_writing(self):
        out = io.StringIO()
        call_command("scan_sell", "--salon-id", str(self.salon.pk),
                     "--code", "SH-001", "--quantity", "12",
                     "--dry-run", stdout=out)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(self.product.current_stock, 10)
        self.assertIn("resulting stock -2", out.getvalue())
        self.assertIn("would be below zero", out.getvalue())

    def test_dry_run_unknown_code_raises_and_records_nothing(self):
        with self.assertRaises(CommandError):
            call_command("scan_sell", salon_id=self.salon.pk,
                         code="999999999999", dry_run=True,
                         stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_default_text_output_unchanged(self):
        out = io.StringIO()
        call_command("scan_sell", salon_id=self.salon.pk,
                     code="012345678905", quantity=3, stdout=out)
        self.assertEqual(
            out.getvalue(),
            f"Sold -3 x Shampoo (product {self.product.pk}): "
            f"current stock 7.\n")

    def test_format_json_parses_and_carries_expected_fields(self):
        out = io.StringIO()
        call_command("scan_sell", "--salon-id", str(self.salon.pk),
                     "--code", "012345678905", "--quantity", "3",
                     "--format", "json", stdout=out)
        text = out.getvalue()
        self.assertEqual(len(text.strip().splitlines()), 1)
        data = json.loads(text)
        movement = StockMovement.objects.order_by("id").last()
        self.assertEqual(data["product_id"], self.product.pk)
        self.assertEqual(data["code"], "012345678905")
        self.assertEqual(data["quantity"], -3)
        self.assertEqual(data["current_stock"], 7)
        self.assertEqual(data["movement_id"], movement.pk)
        self.assertIs(data["below_zero"], False)
        self.assertIs(data["dry_run"], False)

    def test_format_json_below_zero_is_flagged(self):
        out = io.StringIO()
        call_command("scan_sell", salon_id=self.salon.pk,
                     code="012345678905", quantity=12, format="json",
                     stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["current_stock"], -2)
        self.assertIs(data["below_zero"], True)
        self.assertEqual(self.product.current_stock, -2)

    def test_dry_run_format_json_reports_dry_run_and_records_nothing(self):
        out = io.StringIO()
        call_command("scan_sell", salon_id=self.salon.pk,
                     code="SH-001", quantity=3, dry_run=True,
                     format="json", stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["product_id"], self.product.pk)
        self.assertEqual(data["code"], "SH-001")
        self.assertEqual(data["quantity"], -3)
        self.assertEqual(data["current_stock"], 7)
        self.assertIsNone(data["movement_id"])
        self.assertIs(data["below_zero"], False)
        self.assertIs(data["dry_run"], True)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(self.product.current_stock, 10)

    def test_format_json_unknown_code_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("scan_sell", salon_id=self.salon.pk,
                         code="999999999999", format="json",
                         stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 1)

    def test_dry_run_does_not_block_real_sell(self):
        call_command("scan_sell", salon_id=self.salon.pk,
                     code="012345678905", quantity=3, dry_run=True,
                     stdout=io.StringIO())
        call_command("scan_sell", salon_id=self.salon.pk,
                     code="012345678905", quantity=3,
                     stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 2)
        self.assertEqual(self.product.current_stock, 7)
