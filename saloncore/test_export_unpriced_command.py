"""Tests for the export_unpriced management command.

The command is a thin wrapper around
``saloncore.unpriced_export.export_unpriced_services_csv``;
these tests check delegation (stdout/file match the service
output verbatim, with and without a staff level) and clean
failure for invalid input.
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
from saloncore.unpriced_export import export_unpriced_services_csv


class ExportUnpricedCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair", sort_order=1)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Senior", sort_order=2)
        self.junior = StaffLevel.objects.create(
            salon=self.salon, name="Junior", sort_order=1)
        self.unpriced = Service.objects.create(
            category=self.category, name="Unpriced Cut",
            service_minutes=30)
        self.partial = Service.objects.create(
            category=self.category, name="Partial Cut",
            service_minutes=30)
        ServicePrice.objects.create(
            service=self.partial, staff_level=self.junior,
            amount=Decimal("40.00"))

    def test_stdout_csv_matches_service_output(self):
        out = io.StringIO()
        call_command(
            "export_unpriced", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(
            out.getvalue(), export_unpriced_services_csv(self.salon))

    def test_staff_level_stdout_matches_service_output(self):
        out = io.StringIO()
        call_command(
            "export_unpriced", salon_id=self.salon.pk,
            staff_level_id=self.level.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_unpriced_services_csv(
                self.salon, staff_level=self.level))
        self.assertIn("Partial Cut", out.getvalue())

    def test_output_option_writes_file(self):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        try:
            out = io.StringIO()
            call_command(
                "export_unpriced", salon_id=self.salon.pk,
                output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
            self.assertEqual(
                written, export_unpriced_services_csv(self.salon))
            self.assertEqual(out.getvalue(), "")
        finally:
            os.unlink(path)

    def test_unknown_salon_errors_cleanly(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_unpriced", salon_id=999999,
                stdout=io.StringIO())

    def test_unknown_staff_level_errors_cleanly(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_unpriced", salon_id=self.salon.pk,
                staff_level_id=999999, stdout=io.StringIO())

    def test_foreign_staff_level_errors_cleanly(self):
        foreign = StaffLevel.objects.create(
            salon=self.other, name="Foreign", sort_order=1)
        with self.assertRaises(CommandError):
            call_command(
                "export_unpriced", salon_id=self.salon.pk,
                staff_level_id=foreign.pk, stdout=io.StringIO())
