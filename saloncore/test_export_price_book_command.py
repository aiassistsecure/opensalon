"""Tests for the export_price_book management command.

The command is a thin wrapper around
``saloncore.price_book_export.export_price_book_csv``; these
tests check delegation (stdout/file match the service output
verbatim) and clean failure for an unknown salon.
"""
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from saloncore.price_book_export import export_price_book_csv


class ExportPriceBookCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=1)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6", sort_order=2)
        self.service = Service.objects.create(
            category=self.category, name="Single Process Color",
            service_minutes=45, processing_minutes=30,
            finishing_minutes=15)
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.50"), is_from=True)

    def test_stdout_csv_matches_service_output(self):
        out = io.StringIO()
        call_command(
            "export_price_book", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(), export_price_book_csv(self.salon))

    def test_output_option_writes_file(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            out = io.StringIO()
            call_command(
                "export_price_book", salon_id=self.salon.pk,
                output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
            self.assertEqual(written, export_price_book_csv(self.salon))
            self.assertEqual(out.getvalue(), "")
        finally:
            os.unlink(path)

    def test_unknown_salon_errors_cleanly(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_price_book", salon_id=999999,
                stdout=io.StringIO())
