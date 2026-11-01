import io
import os
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.product_sales_export import (
    PRODUCT_SALES_FIELDNAMES,
    export_product_sales_csv,
)
from checkout.models import Sale, SaleItem
from saloncore.models import Salon


class ExportProductSalesCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        p = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        StockMovement.objects.create(
            product=p, kind=StockMovement.Kind.RECEIVE, quantity_delta=6)
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=p,
            description="Shampoo", quantity=2,
            unit_price=Decimal("10.00"))
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        foreign_sale = Sale.objects.create(
            salon=self.other, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=foreign_sale, kind=SaleItem.Kind.PRODUCT,
            product=foreign, description="Foreign", quantity=9,
            unit_price=Decimal("99.00"))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.salon.pk,
                     stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_product_sales_csv(self.salon))
        self.assertEqual(text.splitlines()[0].split(","),
                         PRODUCT_SALES_FIELDNAMES)
        self.assertIn("Shampoo", text)
        self.assertNotIn("Foreign", text)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "product_sales.csv")
            call_command("export_product_sales", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_product_sales_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_product_sales", salon_id=999999,
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "product_sales.csv")
            with self.assertRaises(CommandError):
                call_command("export_product_sales",
                             salon_id=self.salon.pk, output=path,
                             stdout=io.StringIO())
