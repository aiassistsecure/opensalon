import csv
import io
from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.product_sales import product_sales
from catalog.product_sales_export import (
    PRODUCT_SALES_FIELDNAMES,
    export_product_sales_csv,
)
from checkout.models import Sale, SaleItem
from saloncore.models import Salon


def rows_of(text):
    return list(csv.DictReader(io.StringIO(text)))


class ProductSalesExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        for delta in (10, 10, -5):
            StockMovement.objects.create(
                product=self.shampoo,
                kind=StockMovement.Kind.RECEIVE, quantity_delta=delta)
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=self.shampoo,
            description="Shampoo", quantity=5,
            unit_price=Decimal("10.00"))
        Product.objects.create(
            salon=self.salon, name="Serum", sku="SE-002",
            barcode="222333444555", price=Decimal("19.99"))
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        foreign_sale = Sale.objects.create(
            salon=self.other, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=foreign_sale, kind=SaleItem.Kind.PRODUCT,
            product=foreign, description="Foreign", quantity=9,
            unit_price=Decimal("99.00"))

    def test_header_is_fieldnames(self):
        text = export_product_sales_csv(self.salon)
        self.assertEqual(text.splitlines()[0].split(","),
                         PRODUCT_SALES_FIELDNAMES)

    def test_rows_match_service_verbatim(self):
        report = product_sales(self.salon)
        rows = rows_of(export_product_sales_csv(self.salon))
        self.assertEqual(len(rows), len(report.rows))
        for row, expected in zip(rows, report.rows):
            self.assertEqual(int(row["product_id"]), expected.product.pk)
            self.assertEqual(row["product_name"], expected.product.name)
            self.assertEqual(row["sku"], expected.sku)
            self.assertEqual(row["barcode"], expected.barcode)
            self.assertEqual(int(row["units_sold"]), expected.units_sold)
            self.assertEqual(Decimal(row["retail_revenue"]),
                             expected.retail_revenue)
            self.assertEqual(int(row["current_stock"]),
                             expected.current_stock)
            self.assertEqual(Decimal(row["average_stock"]),
                             expected.average_stock)
            self.assertEqual(Decimal(row["stock_turns"]),
                             expected.stock_turns)

    def test_known_values_and_formatting(self):
        rows = rows_of(export_product_sales_csv(self.salon))
        self.assertEqual([r["product_name"] for r in rows],
                         ["Shampoo", "Serum"])
        shampoo = rows[0]
        self.assertEqual(shampoo["units_sold"], "5")
        self.assertEqual(shampoo["retail_revenue"], "50.00")
        self.assertEqual(shampoo["current_stock"], "15")
        self.assertEqual(shampoo["average_stock"], "15.0000")
        self.assertEqual(shampoo["stock_turns"], "0.3333")
        serum = rows[1]
        self.assertEqual(serum["units_sold"], "0")
        self.assertEqual(serum["retail_revenue"], "0.00")
        self.assertEqual(serum["stock_turns"], "0.0000")

    def test_other_salon_never_leaks(self):
        text = export_product_sales_csv(self.salon)
        self.assertNotIn("Foreign", text)

    def test_empty_salon_exports_header_only(self):
        empty = Salon.objects.create(name="Empty Salon")
        text = export_product_sales_csv(empty)
        self.assertEqual(rows_of(text), [])
        self.assertEqual(len(text.splitlines()), 1)
