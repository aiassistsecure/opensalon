"""Tests for the export_rebooking management command.

Synthetic fixtures only -- no real salon/client data. The command
is a thin wrapper around
``clients.rebooking_export.export_rebooking_csv``; these tests
verify stdout/file output matches that service verbatim and that
salon scoping, parameter passthrough, and invalid input handling
apply.
"""
import datetime
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from clients.rebooking_export import export_rebooking_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
REF = datetime.date(2026, 11, 2)


def at(day_offset, hour=12):
    return datetime.datetime.combine(
        REF + datetime.timedelta(days=day_offset),
        datetime.time(hour, 0),
        tzinfo=UTC,
    )


class ExportRebookingCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)

    def _client_with_visit(self, first, last, day_offset=-20, salon=None):
        client = Client.objects.create(
            salon=salon or self.salon, first_name=first, last_name=last)
        start = at(day_offset)
        Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=start, end=start + datetime.timedelta(minutes=45),
            status=Appointment.Status.COMPLETED)
        return client

    def test_stdout_matches_service_output(self):
        self._client_with_visit("Dana", "Due")
        out = io.StringIO()
        call_command(
            "export_rebooking", salon_id=self.salon.id,
            reference_date=REF, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_rebooking_csv(self.salon, reference_date=REF))

    def test_reference_date_string_is_passed_through(self):
        self._client_with_visit("Dana", "Due")
        out = io.StringIO()
        call_command(
            "export_rebooking", salon_id=self.salon.id,
            reference_date="2026-11-02", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_rebooking_csv(self.salon, reference_date=REF))

    def test_lookback_days_is_passed_through(self):
        self._client_with_visit("Wendy", "Window")
        out = io.StringIO()
        call_command(
            "export_rebooking", salon_id=self.salon.id,
            reference_date=REF, lookback_days=14, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_rebooking_csv(
                self.salon, reference_date=REF, lookback_days=14))
        self.assertNotIn("Wendy", out.getvalue())
        out = io.StringIO()
        call_command(
            "export_rebooking", salon_id=self.salon.id,
            reference_date=REF, lookback_days=21, stdout=out)
        self.assertIn("Wendy", out.getvalue())

    def test_window_days_is_passed_through(self):
        self._client_with_visit("Wendy", "Window")
        out = io.StringIO()
        call_command(
            "export_rebooking", salon_id=self.salon.id,
            reference_date=REF, lookback_days=14, window_days=21,
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_rebooking_csv(
                self.salon, reference_date=REF, lookback_days=14,
                window_days=21))
        self.assertIn("Wendy", out.getvalue())

    def test_output_file_matches_service_output(self):
        self._client_with_visit("Dana", "Due")
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as fh:
            path = fh.name
        out = io.StringIO()
        call_command(
            "export_rebooking", salon_id=self.salon.id,
            reference_date=REF, output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(
            data, export_rebooking_csv(self.salon, reference_date=REF))
        self.assertEqual(out.getvalue(), "")

    def test_salon_scoping_excludes_other_salons(self):
        self._client_with_visit("Mina", "Mine")
        self._client_with_visit("Theo", "Theirs", salon=self.other_salon)
        out = io.StringIO()
        call_command(
            "export_rebooking", salon_id=self.salon.id,
            reference_date=REF, stdout=out)
        text = out.getvalue()
        self.assertIn("Mina", text)
        self.assertNotIn("Theo", text)

    def test_no_candidates_exports_header_only(self):
        Client.objects.create(
            salon=self.salon, first_name="Nina", last_name="Never")
        out = io.StringIO()
        call_command(
            "export_rebooking", salon_id=self.salon.id,
            reference_date=REF, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_rebooking_csv(self.salon, reference_date=REF))

    def test_unknown_salon_id_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_rebooking", salon_id=999999, stdout=io.StringIO())

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_rebooking", stdout=io.StringIO())

    def test_invalid_reference_date_raises(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_rebooking", salon_id=self.salon.id,
                reference_date="not-a-date", stdout=io.StringIO())

    def test_unwritable_output_raises(self):
        self._client_with_visit("Dana", "Due")
        with self.assertRaises(CommandError):
            call_command(
                "export_rebooking", salon_id=self.salon.id,
                reference_date=REF, output="/nonexistent-dir/out.csv",
                stdout=io.StringIO())
