import io
import os
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.export import EXPORT_FIELDNAMES, export_products_csv
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class ExportProductsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        p = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.50"))
        StockMovement.objects.create(
            product=p, kind=StockMovement.Kind.RECEIVE, quantity_delta=7)
        Product.objects.create(
            salon=self.salon, name="Balm", sku="BL-002",
            barcode="111222333444", price=Decimal("8.50"))
        Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))

    def test_stdout_matches_service_incl_sku_barcode(self):
        out = io.StringIO()
        call_command("export_products", salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_products_csv(self.salon))
        header = text.splitlines()[0].split(",")
        self.assertEqual(header, EXPORT_FIELDNAMES)
        self.assertIn("sku", header)
        self.assertIn("barcode", header)
        self.assertIn("SH-001", text)
        self.assertIn("012345678905", text)
        self.assertNotIn("Foreign", text)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "products.csv")
            call_command("export_products", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_products_csv(self.salon))
        self.assertIn("sku", text.splitlines()[0])
        self.assertIn("barcode", text.splitlines()[0])
        self.assertNotIn("Foreign", text)

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_products", salon_id=999999,
                         stdout=io.StringIO())
