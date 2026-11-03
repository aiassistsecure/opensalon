import io
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.scanning import scan_receive
from saloncore.models import Salon


class ScanReceiveCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("24.00"))

    def test_happy_path_by_barcode_matches_service(self):
        out = io.StringIO()
        call_command("scan_receive", salon_id=self.salon.pk,
                     code="012345678905", quantity=4, stdout=out)
        movement = StockMovement.objects.get()
        self.assertEqual(movement.kind, StockMovement.Kind.RECEIVE)
        self.assertEqual(movement.quantity_delta, 4)
        self.assertEqual(self.product.current_stock, 4)
        text = out.getvalue()
        self.assertIn("Shampoo", text)
        self.assertIn("current stock 4", text)
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_happy_path_by_sku_defaults_to_one(self):
        out = io.StringIO()
        call_command("scan_receive", salon_id=self.salon.pk,
                     code="SH-001", stdout=out)
        expected = scan_receive(self.salon, "SH-001")
        self.assertTrue(expected.found)
        self.assertEqual(self.product.current_stock, 2)
        self.assertIn("current stock 1", out.getvalue())

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("scan_receive", salon_id=999999,
                         code="012345678905", stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_unknown_code_raises_command_error_and_records_nothing(self):
        with self.assertRaises(CommandError):
            call_command("scan_receive", salon_id=self.salon.pk,
                         code="999999999999", stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_non_positive_quantity_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("scan_receive", salon_id=self.salon.pk,
                         code="012345678905", quantity=0,
                         stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_dry_run_writes_nothing_and_previews_movement(self):
        out = io.StringIO()
        call_command("scan_receive", salon_id=self.salon.pk,
                     code="012345678905", quantity=4, dry_run=True,
                     stdout=out)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(self.product.current_stock, 0)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn("receive", text)
        self.assertIn("+4", text)
        self.assertIn("Shampoo", text)
        self.assertIn(f"product {self.product.pk}", text)
        self.assertIn("resulting stock 4", text)

    def test_dry_run_flag_form_previews_from_existing_stock(self):
        scan_receive(self.salon, "012345678905", quantity=3)
        out = io.StringIO()
        call_command("scan_receive", "--salon-id", str(self.salon.pk),
                     "--code", "SH-001", "--quantity", "2",
                     "--dry-run", stdout=out)
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(self.product.current_stock, 3)
        self.assertIn("resulting stock 5", out.getvalue())

    def test_dry_run_unknown_code_raises_and_records_nothing(self):
        with self.assertRaises(CommandError):
            call_command("scan_receive", salon_id=self.salon.pk,
                         code="999999999999", dry_run=True,
                         stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_dry_run_does_not_block_real_receive(self):
        call_command("scan_receive", salon_id=self.salon.pk,
                     code="012345678905", quantity=4, dry_run=True,
                     stdout=io.StringIO())
        call_command("scan_receive", salon_id=self.salon.pk,
                     code="012345678905", quantity=4,
                     stdout=io.StringIO())
        self.assertEqual(StockMovement.objects.count(), 1)
        self.assertEqual(self.product.current_stock, 4)
