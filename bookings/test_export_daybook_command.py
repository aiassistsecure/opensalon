"""Tests for the export_daybook management command.

The command is a thin wrapper around
``bookings.daybook_export.export_daybook_csv``: these tests
pin that its stdout and file output match that service verbatim
and that unknown salons and bad dates fail cleanly.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.daybook_export import export_daybook, export_daybook_csv
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


class ExportDaybookCommandTests(TestCase):
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
        Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=datetime.datetime.combine(
                DAY, datetime.time(9, 0), tzinfo=UTC),
            end=datetime.datetime.combine(
                DAY, datetime.time(9, 45), tzinfo=UTC))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_daybook", salon_id=self.salon.pk, date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_daybook_csv(self.salon, DAY))

    def test_stdout_matches_service_with_string_date_arg(self):
        out = io.StringIO()
        call_command(
            "export_daybook", "--salon-id", str(self.salon.pk),
            "--date", DAY.isoformat(), stdout=out)
        self.assertEqual(out.getvalue(), export_daybook_csv(self.salon, DAY))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daybook.csv")
            call_command(
                "export_daybook", salon_id=self.salon.pk, date=DAY,
                output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(written, export_daybook_csv(self.salon, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_daybook", salon_id=self.salon.pk + 1000,
                date=DAY, stdout=io.StringIO())

    def test_bad_date_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_daybook", "--salon-id", str(self.salon.pk),
                "--date", "not-a-date", stdout=io.StringIO())

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command(
            "export_daybook", salon_id=self.salon.pk, date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_daybook_csv(self.salon, DAY))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_daybook", salon_id=self.salon.pk, date=DAY,
            format="csv", stdout=out)
        self.assertEqual(out.getvalue(), export_daybook_csv(self.salon, DAY))
        out = io.StringIO()
        call_command(
            "export_daybook", "--salon-id", str(self.salon.pk),
            "--date", DAY.isoformat(), "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), export_daybook_csv(self.salon, DAY))

    def test_json_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_daybook", salon_id=self.salon.pk, date=DAY,
            format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()), export_daybook(self.salon, DAY))
        out = io.StringIO()
        call_command(
            "export_daybook", "--salon-id", str(self.salon.pk),
            "--date", DAY.isoformat(), "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()), export_daybook(self.salon, DAY))

    def test_json_date_filter_composes(self):
        other_day = DAY + datetime.timedelta(days=1)
        out = io.StringIO()
        call_command(
            "export_daybook", salon_id=self.salon.pk, date=other_day,
            format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(
            json.loads(out.getvalue()),
            export_daybook(self.salon, other_day))
        out = io.StringIO()
        call_command(
            "export_daybook", "--salon-id", str(self.salon.pk),
            "--date", DAY.isoformat(), "--format", "json", stdout=out)
        self.assertEqual(
            [row["appointment_id"] for row in json.loads(out.getvalue())],
            [row["appointment_id"]
             for row in export_daybook(self.salon, DAY)])
        self.assertEqual(len(json.loads(out.getvalue())), 1)

    def test_json_output_file_matches_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "daybook.json")
            call_command(
                "export_daybook", salon_id=self.salon.pk, date=DAY,
                format="json", output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written), export_daybook(self.salon, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_daybook", salon_id=self.salon.pk, date=DAY,
                format="xml", stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command(
                "export_daybook", "--salon-id", str(self.salon.pk),
                "--date", DAY.isoformat(), "--format", "xml",
                stdout=io.StringIO())
