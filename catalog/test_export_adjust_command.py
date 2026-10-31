"""Tests for the export_adjust management command.

The command is a thin wrapper around
``catalog.adjust_export.export_stock_adjustments_csv``; these tests
check delegation (stdout/file match the service output verbatim,
as CSV), salon scoping, date filtering, and clean failure for an
unknown salon, an invalid range bound, and an unwritable output.
"""
import csv
import io
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from catalog.adjust_export import (
    ADJUST_FIELDNAMES,
    export_stock_adjustments_csv,
)
from catalog.models import Product, StockMovement
from saloncore.models import Salon


class ExportAdjustCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.day = date(2026, 10, 3)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.product, -2, note="Damaged bottles", on=self.day)
        self.move(self.product, 10, kind=StockMovement.Kind.RECEIVE,
                  on=self.day)
        self.move(self.product, 5, note="Recount",
                  on=self.day + timedelta(days=1))
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        self.move(foreign, 9, note="Foreign recount", on=self.day)

    def move(self, product, delta, kind=StockMovement.Kind.ADJUSTMENT,
             note="", on=None):
        movement = StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta, note=note)
        if on is not None:
            moment = timezone.make_aware(
                datetime(on.year, on.month, on.day, 12, 0))
            StockMovement.objects.filter(pk=movement.pk).update(
                created_at=moment)
        return movement

    def expected_text(self, *args, **kwargs):
        return export_stock_adjustments_csv(*args, **kwargs)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, self.expected_text(self.salon))
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(list(rows[0].keys()), ADJUST_FIELDNAMES)
        self.assertEqual([r["quantity_delta"] for r in rows], ["-2", "5"])
        self.assertEqual([r["note"] for r in rows],
                         ["Damaged bottles", "Recount"])
        self.assertNotIn("Foreign", text)

    def test_date_range_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_adjust", "--salon-id", str(self.salon.pk),
            "--start-date", self.day.isoformat(),
            "--end-date", self.day.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            self.expected_text(self.salon, start=self.day, end=self.day))
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual([r["quantity_delta"] for r in rows], ["-2"])
        after = self.day + timedelta(days=30)
        out = io.StringIO()
        call_command("export_adjust", salon_id=self.salon.pk,
                     start_date=after, end_date=after, stdout=out)
        self.assertEqual(
            out.getvalue(),
            ",".join(ADJUST_FIELDNAMES) + "\n")

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "adjust.csv")
            call_command("export_adjust", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self.expected_text(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_adjust", salon_id=999999,
                         stdout=io.StringIO())

    def test_invalid_bound_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_adjust", salon_id=self.salon.pk,
                         start_date="not-a-date", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "adjust.csv")
            with self.assertRaises(CommandError):
                call_command("export_adjust", salon_id=self.salon.pk,
                             output=path, stdout=io.StringIO())
