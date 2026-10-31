"""Tests for the export_available_slots management command.

The command is a thin wrapper around
``bookings.availability_export.export_available_slots_csv``:
these tests pin that its stdout and file output match that
service verbatim, that service / online-only filters pass
through, that it scopes to the requested salon, and that
unknown salons / services, missing dates, service errors, and
unwritable output fail cleanly.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.availability_export import export_available_slots_csv
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


class ExportAvailableSlotsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_available_slots", salon_id=self.salon.pk,
            date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_available_slots_csv(self.salon, DAY))

    def test_stdout_matches_service_with_string_date_arg(self):
        out = io.StringIO()
        call_command(
            "export_available_slots", "--salon-id", str(self.salon.pk),
            "--date", DAY.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_available_slots_csv(self.salon, DAY))

    def test_service_filter_passes_through_to_service(self):
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=datetime.datetime.combine(
                DAY, datetime.time(12, 0), tzinfo=UTC),
            end=datetime.datetime.combine(
                DAY, datetime.time(13, 0), tzinfo=UTC))
        long_service = Service.objects.create(
            category=self.service.category, name="Long",
            service_minutes=300)
        out = io.StringIO()
        call_command(
            "export_available_slots", salon_id=self.salon.pk,
            date=DAY, service_id=long_service.pk, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_available_slots_csv(
                self.salon, DAY, service=long_service))
        self.assertNotEqual(
            out.getvalue(), export_available_slots_csv(self.salon, DAY))

    def test_online_only_passes_through_to_service(self):
        offline = StaffMember.objects.create(
            salon=self.salon, display_name="Offline",
            online_bookable=False)
        RosterPattern.objects.create(
            staff_member=offline, weekday=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0))
        out = io.StringIO()
        call_command(
            "export_available_slots", "--salon-id", str(self.salon.pk),
            "--date", DAY.isoformat(), "--online-only", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_available_slots_csv(
                self.salon, DAY, online_only=True))
        self.assertNotIn("Offline", out.getvalue())

    def test_salon_scoping(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        RosterPattern.objects.create(
            staff_member=other_staff, weekday=0,
            start_time=datetime.time(10, 0),
            end_time=datetime.time(14, 0))
        out = io.StringIO()
        call_command(
            "export_available_slots", salon_id=other.pk,
            date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), export_available_slots_csv(other, DAY))
        self.assertIn(f"{other.pk},", out.getvalue())
        self.assertIn("Other Stylist", out.getvalue())

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "available_slots.csv")
            call_command(
                "export_available_slots", salon_id=self.salon.pk,
                date=DAY, output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_available_slots_csv(self.salon, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_available_slots", salon_id=self.salon.pk + 1000,
                date=DAY, stdout=io.StringIO())

    def test_unknown_service_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_available_slots", salon_id=self.salon.pk,
                date=DAY, service_id=self.service.pk + 1000,
                stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "slots.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_available_slots", salon_id=self.salon.pk,
                    date=DAY, output=path, stdout=io.StringIO())

    def test_no_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_available_slots", salon_id=self.salon.pk,
                stdout=io.StringIO())

    def test_bad_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_available_slots",
                "--salon-id", str(self.salon.pk),
                "--date", "not-a-date", stdout=io.StringIO())
