import io
import os
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.low_stock_export import (
    LOW_STOCK_FIELDNAMES,
    export_low_stock_csv,
)
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class ExportLowStockCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        p = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        StockMovement.objects.create(
            product=p, kind=StockMovement.Kind.RECEIVE, quantity_delta=2)
        Product.objects.create(
            salon=self.salon, name="Serum", sku="SE-002",
            barcode="222333444555", price=Decimal("19.99"))
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        StockMovement.objects.create(
            product=foreign, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=1)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_low_stock", salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_low_stock_csv(self.salon))
        header = text.splitlines()[0].split(",")
        self.assertEqual(header, LOW_STOCK_FIELDNAMES)
        self.assertIn("Shampoo", text)
        self.assertNotIn("Foreign", text)

    def test_threshold_matches_service(self):
        out = io.StringIO()
        call_command("export_low_stock", salon_id=self.salon.pk,
                     threshold=0, stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text, export_low_stock_csv(self.salon, threshold=0))
        self.assertIn("Serum", text)
        self.assertNotIn("Shampoo", text)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "low_stock.csv")
            call_command("export_low_stock", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_low_stock_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_low_stock", salon_id=999999,
                         stdout=io.StringIO())

    def test_negative_threshold_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_low_stock", salon_id=self.salon.pk,
                         threshold=-1, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "low_stock.csv")
            with self.assertRaises(CommandError):
                call_command("export_low_stock", salon_id=self.salon.pk,
                             output=path, stdout=io.StringIO())
