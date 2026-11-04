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
            salon=self.salon, name="Retired Wax", sku="RW-003",
            barcode="222333444555", price=Decimal("6.00"), active=False)
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

    def test_default_excludes_inactive(self):
        out = io.StringIO()
        call_command("export_products", salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_products_csv(self.salon))
        self.assertEqual(
            text, export_products_csv(self.salon, include_inactive=False))
        self.assertNotIn("Retired Wax", text)
        self.assertNotIn("RW-003", text)

    def test_include_inactive_matches_service(self):
        out = io.StringIO()
        call_command("export_products", salon_id=self.salon.pk,
                     include_inactive=True, stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text, export_products_csv(self.salon, include_inactive=True))
        self.assertIn("Retired Wax", text)
        self.assertIn("RW-003", text)
        self.assertNotIn("Foreign", text)

    def test_include_inactive_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_products", "--salon-id", str(self.salon.pk),
                     "--include-inactive", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_products_csv(self.salon, include_inactive=True))
        self.assertIn("Retired Wax", out.getvalue())

    def test_include_inactive_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "products.csv")
            call_command("export_products", salon_id=self.salon.pk,
                         include_inactive=True, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(
            text, export_products_csv(self.salon, include_inactive=True))
        self.assertIn("Retired Wax", text)

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_products", salon_id=999999,
                         stdout=io.StringIO())


class ExportProductsProductTypeCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        Product.objects.create(
            salon=self.salon, name="Retail Shampoo",
            price=Decimal("10.50"), product_type="retail")
        Product.objects.create(
            salon=self.salon, name="Backbar Shampoo",
            price=Decimal("10.50"), product_type="backbar",
            category_name="retail")
        Product.objects.create(
            salon=self.salon, name="Retired Retail", price=Decimal("6.00"),
            active=False, product_type="retail")

    def test_product_type_kwarg_matches_service(self):
        out = io.StringIO()
        call_command("export_products", salon_id=self.salon.pk,
                     product_type="retail", stdout=out)
        self.assertEqual(out.getvalue(), export_products_csv(
            self.salon, product_type="retail"))
        self.assertIn("Retail Shampoo", out.getvalue())
        self.assertNotIn("Backbar Shampoo", out.getvalue())
        self.assertNotIn("Retired Retail", out.getvalue())

    def test_product_type_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_products", "--salon-id", str(self.salon.pk),
                     "--product-type", "retail", stdout=out)
        self.assertEqual(out.getvalue(), export_products_csv(
            self.salon, product_type="retail"))

    def test_product_type_composes_with_include_inactive(self):
        out = io.StringIO()
        call_command("export_products", "--salon-id", str(self.salon.pk),
                     "--product-type", "retail", "--include-inactive",
                     stdout=out)
        self.assertEqual(out.getvalue(), export_products_csv(
            self.salon, include_inactive=True, product_type="retail"))
        self.assertIn("Retired Retail", out.getvalue())
        self.assertNotIn("Backbar Shampoo", out.getvalue())

    def test_product_type_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "products.csv")
            call_command("export_products", salon_id=self.salon.pk,
                         product_type="retail", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_products_csv(
            self.salon, product_type="retail"))
