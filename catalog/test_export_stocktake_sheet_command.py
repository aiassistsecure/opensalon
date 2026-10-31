"""Tests for the catalog export_stocktake_sheet management command.

The command is a thin wrapper around
``catalog.stocktake_sheet_export.export_stocktake_sheet_csv``:
these tests pin that its stdout and file output match that
service verbatim, that it scopes to the requested salon, and
that unknown salons and unwritable output fail cleanly as
``CommandError``.

These tests load the catalog command class explicitly via
``load_command_class("catalog", "export_stocktake_sheet")`` and
pass that instance to ``call_command`` -- pinning this app's
command, not the global name resolution.
"""
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.stocktake_sheet_export import (
    STOCKTAKE_SHEET_FIELDNAMES,
    export_stocktake_sheet_csv,
)
from saloncore.models import Salon


def _cmd():
    return load_command_class("catalog", "export_stocktake_sheet")


class ExportStocktakeSheetCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.shampoo = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("18.50"))
        StockMovement.objects.create(
            product=self.shampoo,
            kind=StockMovement.Kind.RECEIVE, quantity_delta=10)
        StockMovement.objects.create(
            product=self.shampoo,
            kind=StockMovement.Kind.SALE, quantity_delta=-7)
        Product.objects.create(
            salon=self.salon, name="Conditioner", sku="CN-002",
            barcode="012345678906", price=Decimal("19.99"))
        Product.objects.create(
            salon=self.salon, name="Retired", sku="RT-999",
            barcode="999", price=Decimal("5.00"), active=False)
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999999", price=Decimal("1.00"))
        StockMovement.objects.create(
            product=foreign,
            kind=StockMovement.Kind.RECEIVE, quantity_delta=9)

    def test_stdout_matches_service_verbatim(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_stocktake_sheet_csv(self.salon))
        self.assertEqual(
            text.splitlines()[0],
            ",".join(STOCKTAKE_SHEET_FIELDNAMES))
        self.assertIn("Shampoo", text)
        self.assertIn("Conditioner", text)
        self.assertNotIn("Foreign", text)
        self.assertNotIn("Retired", text)

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(_cmd(), "--salon-id", str(self.salon.pk),
                     stdout=out)
        self.assertEqual(
            out.getvalue(), export_stocktake_sheet_csv(self.salon))

    def test_salon_scoping_matches_service(self):
        out = io.StringIO()
        call_command(_cmd(), salon_id=self.other.pk, stdout=out)
        self.assertEqual(
            out.getvalue(), export_stocktake_sheet_csv(self.other))
        self.assertIn("Foreign", out.getvalue())
        self.assertNotIn("Shampoo", out.getvalue())

    def test_empty_salon_is_header_only(self):
        empty = Salon.objects.create(name="Empty Salon")
        out = io.StringIO()
        call_command(_cmd(), salon_id=empty.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, export_stocktake_sheet_csv(empty))
        self.assertEqual(
            text, ",".join(STOCKTAKE_SHEET_FIELDNAMES) + "\n")

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "stocktake_sheet.csv")
            call_command(_cmd(), salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, export_stocktake_sheet_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(_cmd(), salon_id=999999,
                         stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "sheet.csv")
            with self.assertRaises(CommandError):
                call_command(_cmd(), salon_id=self.salon.pk,
                             output=path, stdout=io.StringIO())
