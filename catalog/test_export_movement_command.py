"""Tests for the export_movement management command.

The command is a thin wrapper around
``catalog.movement_export.export_movement_export``; these tests
check delegation (stdout/file match the service output verbatim,
as JSON), salon scoping, date filtering, and clean failure for an
unknown salon, an invalid range bound, and an unwritable output.
"""
import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from catalog.models import Product, StockMovement
from catalog.movement_export import export_movement_export
from saloncore.models import Salon


class ExportMovementCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.day = date(2026, 10, 3)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("10.00"))
        self.move(self.product, 10, note="delivery", on=self.day)
        self.move(self.product, -3, kind=StockMovement.Kind.SALE,
                  on=self.day)
        foreign = Product.objects.create(
            salon=self.other, name="Foreign", sku="FR-999",
            barcode="999", price=Decimal("1.00"))
        self.move(foreign, 9, on=self.day)

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE,
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
        return json.dumps(
            export_movement_export(*args, **kwargs), indent=2) + "\n"

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk, stdout=out)
        text = out.getvalue()
        self.assertEqual(text, self.expected_text(self.salon))
        data = json.loads(text)
        self.assertEqual([m["product_name"] for m in data["movements"]],
                         ["Shampoo", "Shampoo"])
        self.assertEqual(data["totals"][0]["net_delta"], 7)
        self.assertNotIn("Foreign", text)

    def test_date_range_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_movement", "--salon-id", str(self.salon.pk),
            "--start-date", self.day.isoformat(),
            "--end-date", self.day.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            self.expected_text(self.salon, start=self.day, end=self.day))
        after = self.day + timedelta(days=1)
        out = io.StringIO()
        call_command("export_movement", salon_id=self.salon.pk,
                     start_date=after, stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         {"movements": [], "totals": []})

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "movement.json")
            call_command("export_movement", salon_id=self.salon.pk,
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        self.assertEqual(text, self.expected_text(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_movement", salon_id=999999,
                         stdout=io.StringIO())

    def test_invalid_bound_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_movement", salon_id=self.salon.pk,
                         start_date="not-a-date", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "movement.json")
            with self.assertRaises(CommandError):
                call_command("export_movement", salon_id=self.salon.pk,
                             output=path, stdout=io.StringIO())
