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
from datetime import date, datetime
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

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


class ExportStockHistoryWindowCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.day1 = date(2026, 1, 5)
        self.day2 = date(2026, 1, 6)
        self.day3 = date(2026, 1, 7)
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move_on(self.shampoo, 10, self.day1)
        self.move_on(self.shampoo, -3, self.day2,
                     kind=StockMovement.Kind.SALE)
        self.move_on(self.shampoo, -2, self.day3,
                     kind=StockMovement.Kind.ADJUSTMENT)
        self.serum = Product.objects.create(
            salon=self.salon, name="Serum", sku="SE-002",
            barcode="222333444555", price=Decimal("19.99"))
        self.move_on(self.serum, 99, self.day2)

    def move_on(self, product, delta, on, kind=StockMovement.Kind.RECEIVE):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta)
        moment = timezone.make_aware(
            datetime(on.year, on.month, on.day, 12, 0))
        StockMovement.objects.filter(pk=movement.pk).update(
            created_at=moment)
        return movement

    def test_window_flags_match_service(self):
        out = io.StringIO()
        call_command(
            "export_stock_history", "--salon-id", str(self.salon.pk),
            "--product-id", str(self.shampoo.pk),
            "--start-date", self.day2.isoformat(),
            "--end-date", self.day3.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_stock_history_csv(
                self.salon, self.shampoo.pk,
                start=self.day2, end=self.day3))
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual([r["quantity_delta"] for r in rows], ["-3", "-2"])
        self.assertEqual([r["running_balance"] for r in rows], ["7", "5"])

    def test_window_kwargs_and_alias_flags_match_service(self):
        out = io.StringIO()
        call_command("export_stock_history", salon_id=self.salon.pk,
                     product_id=self.shampoo.pk,
                     start_date=self.day2, end_date=self.day2, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_stock_history_csv(
                self.salon, self.shampoo.pk,
                start=self.day2, end=self.day2))
        out = io.StringIO()
        call_command(
            "export_stock_history", "--salon-id", str(self.salon.pk),
            "--product-id", str(self.shampoo.pk),
            "--start", self.day3.isoformat(),
            "--end", self.day3.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_stock_history_csv(
                self.salon, self.shampoo.pk,
                start=self.day3, end=self.day3))

    def test_no_window_is_previous_output_and_invalid_date_fails(self):
        out = io.StringIO()
        call_command("export_stock_history", salon_id=self.salon.pk,
                     product_id=self.shampoo.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_stock_history_csv(self.salon, self.shampoo.pk))
        with self.assertRaises(CommandError):
            call_command("export_stock_history", salon_id=self.salon.pk,
                         product_id=self.shampoo.pk,
                         start_date="not-a-date", stdout=io.StringIO())
