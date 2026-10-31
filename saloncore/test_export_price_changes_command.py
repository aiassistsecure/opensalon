"""Tests for the export_price_changes management command.

The command is a thin wrapper around
``saloncore.price_change_export.export_price_changes_csv``; these
tests check delegation (stdout/file match the service output
verbatim), clean failure for an unknown salon, and date filtering.
"""
import io
import os
import tempfile
from datetime import timedelta
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from saloncore.price_change_export import export_price_changes_csv


class ExportPriceChangesCommandTests(TestCase):
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
        self.price = ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.50"), is_from=True)
        self.change = PriceChange.objects.create(
            service_price=self.price, old_amount=Decimal("85.50"),
            new_amount=Decimal("90.00"), changed_by="Mark",
            note="Annual increase")
        self.change.refresh_from_db()
        self.today = timezone.localdate(self.change.changed_at)

    def test_stdout_csv_matches_service_output(self):
        out = io.StringIO()
        call_command(
            "export_price_changes", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(), export_price_changes_csv(self.salon))

    def test_output_option_writes_file(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            out = io.StringIO()
            call_command(
                "export_price_changes", salon_id=self.salon.pk,
                output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
            self.assertEqual(
                written, export_price_changes_csv(self.salon))
            self.assertEqual(out.getvalue(), "")
        finally:
            os.unlink(path)

    def test_unknown_salon_errors_cleanly(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_price_changes", salon_id=999999,
                stdout=io.StringIO())

    def test_date_filtering_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_price_changes", "--salon-id", str(self.salon.pk),
            "--start-date", self.today.isoformat(),
            "--end-date", self.today.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_price_changes_csv(
                self.salon, start=self.today, end=self.today))
        self.assertIn("Annual increase", out.getvalue())

    def test_date_filtering_excludes_out_of_range(self):
        after = self.today + timedelta(days=1)
        out = io.StringIO()
        call_command(
            "export_price_changes", salon_id=self.salon.pk,
            start_date=after, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_price_changes_csv(self.salon, start=after))
        self.assertNotIn("Annual increase", out.getvalue())
