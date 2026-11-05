"""Tests for the catalog export_product_sales command --format.

Pins that CSV output is byte-identical to the historical output
(hardcoded expected string and the ``export_product_sales_csv``
service), that JSON parses to the dict rows from the new twin
``export_product_sales`` -- the same rows the CSV is built
from -- serialised with ``DjangoJSONEncoder`` (indent=2 +
trailing newline), and that unknown formats fail cleanly.
Windowed exports keep their documentation columns in both
formats.
"""
import csv
import io
import json
import os
import tempfile
from datetime import date
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.product_sales_export import (
    PRODUCT_SALES_FIELDNAMES,
    export_product_sales,
    export_product_sales_csv,
)
from checkout.models import Sale, SaleItem
from saloncore.models import Salon

START = date(2020, 1, 1)
END = date(2030, 1, 1)


def _expected_json(salon, **kw):
    return json.dumps(export_product_sales(salon, **kw), indent=2,
                      cls=DjangoJSONEncoder) + "\n"


def _parsed(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportProductSalesFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.empty = Salon.objects.create(name="Empty Salon")
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        for delta in (10, 10, -5):
            StockMovement.objects.create(
                product=self.shampoo, kind=StockMovement.Kind.RECEIVE,
                quantity_delta=delta)
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=self.shampoo,
            description="Shampoo", quantity=5,
            unit_price=Decimal("10.00"))
        self.serum = Product.objects.create(
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

    def _pinned_csv(self):
        return (
            ",".join(PRODUCT_SALES_FIELDNAMES) + "\n"
            f"{self.shampoo.pk},Shampoo,SH-001,012345678905,5,"
            "50.00,15,15.0000,0.3333\n"
            f"{self.serum.pk},Serum,SE-002,222333444555,0,"
            "0.00,0,0.0000,0.0000\n"
        )

    def test_csv_service_is_byte_identical_to_pinned_output(self):
        self.assertEqual(export_product_sales_csv(self.salon),
                         self._pinned_csv())

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.salon.pk,
                     stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())
        self.assertEqual(out.getvalue(),
                         export_product_sales_csv(self.salon))

    def test_explicit_csv_format_kwargs_matches_service(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.salon.pk,
                     format="csv", stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_explicit_csv_format_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_product_sales", "--salon-id",
                     str(self.salon.pk), "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), self._pinned_csv())

    def test_dict_rows_mirror_csv_rows_exactly(self):
        rows = export_product_sales(self.salon)
        parsed = list(csv.DictReader(io.StringIO(
            export_product_sales_csv(self.salon))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual([list(row) for row in rows],
                         [PRODUCT_SALES_FIELDNAMES] * len(rows))
        self.assertEqual(rows[0]["retail_revenue"], "50.00")
        self.assertEqual(rows[0]["average_stock"], "15.0000")
        self.assertEqual(rows[0]["stock_turns"], "0.3333")
        self.assertIsInstance(rows[0]["units_sold"], int)
        self.assertIsInstance(rows[0]["current_stock"], int)

    def test_json_parses_and_equals_dict_twin(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.salon.pk,
                     format="json", stdout=out)
        rows = export_product_sales(self.salon)
        self.assertEqual(json.loads(out.getvalue()), _parsed(rows))
        self.assertEqual(out.getvalue(), _expected_json(self.salon))
        self.assertIn("Shampoo", out.getvalue())
        self.assertNotIn("Foreign", out.getvalue())

    def test_json_rows_equal_csv_rows(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.salon.pk,
                     format="json", stdout=out)
        json_rows = json.loads(out.getvalue())
        csv_rows = list(csv.DictReader(io.StringIO(
            export_product_sales_csv(self.salon))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in json_rows],
            csv_rows)

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command("export_product_sales", "--salon-id",
                     str(self.salon.pk), "--format", "json", stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.salon))

    def test_json_output_file(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "product_sales.json")
            call_command("export_product_sales", salon_id=self.salon.pk,
                         format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, _expected_json(self.salon))
        self.assertEqual(json.loads(text),
                         _parsed(export_product_sales(self.salon)))
        self.assertEqual(out.getvalue(), "")

    def test_csv_output_file_is_byte_identical(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "product_sales.csv")
            call_command("export_product_sales", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self._pinned_csv())
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_json_and_csv(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.empty.pk,
                     format="json", stdout=out)
        self.assertEqual(out.getvalue(), "[]\n")
        self.assertEqual(export_product_sales(self.empty), [])
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.empty.pk,
                     stdout=out)
        self.assertEqual(out.getvalue(),
                         ",".join(PRODUCT_SALES_FIELDNAMES) + "\n")

    def test_windowed_dict_and_csv_mirror(self):
        kw = dict(start_date=START, end_date=END)
        rows = export_product_sales(self.salon, **kw)
        parsed = list(csv.DictReader(io.StringIO(
            export_product_sales_csv(self.salon, **kw))))
        self.assertEqual(
            [{k: str(v) for k, v in row.items()} for row in rows],
            parsed)
        self.assertEqual(rows[0]["sales_start_date"], "2020-01-01")
        self.assertEqual(rows[0]["sales_end_date"], "2030-01-01")
        self.assertEqual(rows[0]["stock_scope"], "all_time")
        self.assertEqual(rows[0]["units_sold"], 5)

    def test_windowed_json_via_command(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.salon.pk,
                     format="json", start_date=START, end_date=END,
                     stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(
            self.salon, start_date=START, end_date=END))
        self.assertIn('"stock_scope": "all_time"', out.getvalue())

    def test_windowed_csv_command_is_byte_identical(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.salon.pk,
                     start_date=START, end_date=END, stdout=out)
        self.assertEqual(out.getvalue(), export_product_sales_csv(
            self.salon, start_date=START, end_date=END))

    def test_json_scopes_to_salon(self):
        out = io.StringIO()
        call_command("export_product_sales", salon_id=self.other.pk,
                     format="json", stdout=out)
        self.assertEqual(out.getvalue(), _expected_json(self.other))
        self.assertIn("Foreign", out.getvalue())

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_product_sales", salon_id=self.salon.pk,
                         format="xml", stdout=io.StringIO())

    def test_unknown_format_via_cli_is_rejected(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_product_sales", "--salon-id",
                         str(self.salon.pk), "--format", "xml",
                         stdout=io.StringIO())

    def test_unknown_salon_raises_command_error_json(self):
        with self.assertRaises(CommandError):
            call_command("export_product_sales", salon_id=999999,
                         format="json", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "out.json")
            with self.assertRaises(CommandError):
                call_command("export_product_sales",
                             salon_id=self.salon.pk, format="json",
                             output=path, stdout=io.StringIO())

    def test_reversed_window_json_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_product_sales", salon_id=self.salon.pk,
                         format="json", start_date=END, end_date=START,
                         stdout=io.StringIO())
