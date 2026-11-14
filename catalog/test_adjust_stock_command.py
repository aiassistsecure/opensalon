import io
import json
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

    def test_dry_run_invalid_writes_nothing_before_equals_after(self):
        before = StockMovement.objects.count()
        for kwargs in ({"delta": 0, "reason": "No-op"},
                       {"delta": 1, "reason": "   "}):
            with self.assertRaises(CommandError):
                call_command(
                    "adjust_stock", salon_id=self.salon.pk,
                    product_id=self.product.pk, dry_run=True,
                    stdout=io.StringIO(), **kwargs)
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(self.product.current_stock, 10)

    def test_dry_run_below_zero_raises_and_writes_nothing(self):
        before = StockMovement.objects.count()
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=self.salon.pk,
                         product_id=self.product.pk, delta=-11,
                         reason="Write-off", dry_run=True,
                         stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(self.product.current_stock, 10)

    def test_explicit_text_format_matches_default(self):
        out_default, out_text = io.StringIO(), io.StringIO()
        # Use dry-run so both calls preview the same state.
        for out in (out_default, out_text):
            kwargs = dict(salon_id=self.salon.pk,
                          product_id=self.product.pk, delta=-3,
                          reason="Damaged bottles", dry_run=True,
                          stdout=out)
            if out is out_text:
                kwargs["format"] = "text"
            call_command("adjust_stock", **kwargs)
        self.assertEqual(out_default.getvalue(), out_text.getvalue())
        self.assertIn("resulting stock 7", out_text.getvalue())
        self.assertNotIn("{", out_text.getvalue())

    def test_format_json_parses_and_carries_expected_fields(self):
        out = io.StringIO()
        call_command("adjust_stock", "--salon-id", str(self.salon.pk),
                     "--product-id", str(self.product.pk),
                     "--delta", "-3", "--reason", "Damaged bottles",
                     "--format", "json", stdout=out)
        text = out.getvalue()
        self.assertEqual(len(text.strip().splitlines()), 1)
        data = json.loads(text)
        (movement,) = self.adjustments()
        self.assertEqual(movement.quantity_delta, -3)
        self.assertEqual(data["product_id"], self.product.pk)
        self.assertEqual(data["salon_id"], self.salon.pk)
        self.assertEqual(data["name"], "Shampoo")
        self.assertEqual(data["delta"], -3)
        self.assertEqual(data["reason"], "Damaged bottles")
        self.assertEqual(data["current_stock"], 7)
        self.assertIs(data["dry_run"], False)
        self.assertEqual(self.product.current_stock, 7)

    def test_dry_run_format_json_reports_dry_run_and_writes_nothing(self):
        before = StockMovement.objects.count()
        out = io.StringIO()
        call_command("adjust_stock", salon_id=self.salon.pk,
                     product_id=self.product.pk, delta=-4,
                     reason="Broken in transit", dry_run=True,
                     format="json", stdout=out)
        text = out.getvalue()
        self.assertEqual(len(text.strip().splitlines()), 1)
        data = json.loads(text)
        self.assertEqual(data["product_id"], self.product.pk)
        self.assertEqual(data["salon_id"], self.salon.pk)
        self.assertEqual(data["name"], "Shampoo")
        self.assertEqual(data["delta"], -4)
        self.assertEqual(data["reason"], "Broken in transit")
        self.assertEqual(data["current_stock"], 6)
        self.assertIs(data["dry_run"], True)
        self.assertEqual(StockMovement.objects.count(), before)
        self.assertEqual(self.adjustments().count(), 0)
        self.assertEqual(self.product.current_stock, 10)

    def test_dry_run_text_output_unchanged_with_format_text(self):
        out = io.StringIO()
        call_command("adjust_stock", salon_id=self.salon.pk,
                     product_id=self.product.pk, delta=-4,
                     reason="Broken in transit", dry_run=True,
                     format="text", stdout=out)
        self.assertIn("Dry run: would record adjustment movement",
                      out.getvalue())
        self.assertIn("resulting stock 6", out.getvalue())
        self.assertEqual(self.adjustments().count(), 0)

    def test_format_json_errors_still_raise_command_error(self):
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=999999,
                         product_id=self.product.pk, delta=1,
                         reason="Fix", format="json",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=self.salon.pk,
                         product_id=self.product.pk, delta=-11,
                         reason="Write-off", format="json",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("adjust_stock", salon_id=self.salon.pk,
                         product_id=self.product.pk, delta=-11,
                         reason="Write-off", dry_run=True,
                         format="json", stdout=io.StringIO())
        self.assertEqual(self.adjustments().count(), 0)
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
