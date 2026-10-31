"""Tests for the export_stock_history management command.

The command is a thin wrapper around
``catalog.history_export.export_stock_history_csv``; these tests
check delegation (stdout/file match the service output verbatim,
as CSV), salon scoping, and clean failure for an unknown salon,
a foreign or missing product, and an unwritable output.
"""
import csv
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.history_export import (
    HISTORY_FIELDNAMES,
    export_stock_history_csv,
)
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class ExportStockHistoryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.shampoo, 10)
        self.move(self.shampoo, -3, kind=StockMovement.Kind.SALE)
        self.serum = Product.objects.create(
            salon=self.salon, name="Serum", sku="SE-002",
            barcode="222333444555", price=Decimal("19.99"))
        self.move(self.serum, 99)
        self.foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        self.move(self.foreign, 9)

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE):
        return StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta)

    def expected_text(self, salon, product):
        return export_stock_history_csv(salon, product)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_stock_history", salon_id=self.salon.pk,
                     product_id=self.shampoo.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(
            text, self.expected_text(self.salon, self.shampoo.pk))
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(rows[0].keys()), HISTORY_FIELDNAMES)
        self.assertEqual([r["quantity_delta"] for r in rows],
                         ["10", "-3"])
        self.assertEqual([r["running_balance"] for r in rows],
                         ["10", "7"])
        self.assertNotIn("Serum", text)
        self.assertNotIn("Foreign", text)

    def test_product_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_stock_history", "--salon-id", str(self.salon.pk),
            "--product-id", str(self.shampoo.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            self.expected_text(self.salon, self.shampoo.pk))

    def test_product_instance_matches_service(self):
        out = io.StringIO()
        call_command("export_stock_history", salon_id=self.salon.pk,
                     product_id=self.shampoo, stdout=out)
        self.assertEqual(
            out.getvalue(), self.expected_text(self.salon, self.shampoo))

    def test_no_product_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_stock_history",
                         salon_id=self.salon.pk, stdout=io.StringIO())

    def test_salon_scoping_foreign_product_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_stock_history", salon_id=self.salon.pk,
                         product_id=self.foreign.pk,
                         stdout=io.StringIO())

    def test_unknown_product_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_stock_history", salon_id=self.salon.pk,
                         product_id=999999, stdout=io.StringIO())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "stock_history.csv")
            call_command("export_stock_history", salon_id=self.salon.pk,
                         product_id=self.shampoo.pk, output=path,
                         stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(
            text, self.expected_text(self.salon, self.shampoo.pk))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_stock_history", salon_id=999999,
                         product_id=self.shampoo.pk,
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "stock_history.csv")
            with self.assertRaises(CommandError):
                call_command("export_stock_history",
                             salon_id=self.salon.pk,
                             product_id=self.shampoo.pk, output=path,
                             stdout=io.StringIO())
