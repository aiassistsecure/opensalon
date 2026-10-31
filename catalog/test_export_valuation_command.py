import io
import os
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.valuation_export import (
    VALUATION_FIELDNAMES,
    export_stock_valuation_csv,
)
from saloncore.models import Salon


class ExportValuationCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        p = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        StockMovement.objects.create(
            product=p, kind=StockMovement.Kind.RECEIVE, quantity_delta=6)
        Product.objects.create(
            salon=self.salon, name="Serum", sku="SE-002",
            barcode="222333444555", price=Decimal("19.99"))
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        StockMovement.objects.create(
            product=foreign, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=5)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_valuation", salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_stock_valuation_csv(self.salon))
        header = text.splitlines()[0].split(",")
        self.assertEqual(header, VALUATION_FIELDNAMES)
        self.assertIn("Shampoo", text)
        self.assertNotIn("Foreign", text)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "valuation.csv")
            call_command("export_valuation", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_stock_valuation_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_valuation", salon_id=999999,
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "valuation.csv")
            with self.assertRaises(CommandError):
                call_command("export_valuation", salon_id=self.salon.pk,
                             output=path, stdout=io.StringIO())
