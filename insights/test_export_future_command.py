import csv
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from insights.future_export import (
    export_future_appointments_value,
    export_future_appointments_value_csv,
)
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

AS_OF = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=ZoneInfo("UTC"))


class ExportFutureCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Example Salon", timezone="UTC")

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_future", salon_id=self.salon.pk,
            as_of=AS_OF, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_future_appointments_value_csv(self.salon, AS_OF))

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            "export_future", "--salon-id", str(self.salon.pk),
            "--as-of", AS_OF.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_future_appointments_value_csv(self.salon, AS_OF))

    def test_stdout_defaults_produce_service_shape(self):
        out = io.StringIO()
        call_command(
            "export_future", salon_id=self.salon.pk, stdout=out)
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(len(rows), 7)
        for row in rows:
            self.assertEqual(row["value"], "0.00")
            self.assertEqual(row["total"], "0.00")
            self.assertEqual(row["total_count"], "0")

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "future.csv")
            call_command(
                "export_future", salon_id=self.salon.pk,
                as_of=AS_OF, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written,
            export_future_appointments_value_csv(self.salon, AS_OF))
        self.assertEqual(out.getvalue(), "")

    def test_as_of_pass_through_with_appointment(self):
        level = StaffLevel.objects.create(
            salon=self.salon, name="Level 1")
        staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            staff_level=level)
        client = Client.objects.create(
            salon=self.salon, first_name="C", last_name="Test")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        ServicePrice.objects.create(
            service=service, staff_level=level,
            amount=Decimal("85.00"))
        start = AS_OF + datetime.timedelta(days=1)
        Appointment.objects.create(
            client=client, staff_member=staff, service=service,
            start=start, end=start + datetime.timedelta(minutes=45),
            status=Appointment.Status.BOOKED)

        out = io.StringIO()
        call_command(
            "export_future", salon_id=self.salon.pk,
            as_of=AS_OF, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_future_appointments_value_csv(self.salon, AS_OF))
        rows = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(rows[1]["value"], "85.00")
        self.assertEqual(rows[0]["total"], "85.00")

        # A later as-of excludes the appointment, verbatim.
        later = AS_OF + datetime.timedelta(days=2)
        out = io.StringIO()
        call_command(
            "export_future", salon_id=self.salon.pk,
            as_of=later, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_future_appointments_value_csv(self.salon, later))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_future", salon_id=self.salon.pk + 999,
                as_of=AS_OF, stdout=io.StringIO())

    def test_invalid_as_of_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_future", salon_id=self.salon.pk,
                as_of="not-a-datetime", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_future", "--salon-id", str(self.salon.pk),
                "--as-of", "2026-13-40", stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "future.csv")
            with self.assertRaises(CommandError):
                call_command(
                    "export_future", salon_id=self.salon.pk,
                    as_of=AS_OF, output=path, stdout=io.StringIO())

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command(
            "export_future", salon_id=self.salon.pk,
            as_of=AS_OF, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_future_appointments_value_csv(self.salon, AS_OF))

    def test_explicit_csv_format_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_future", salon_id=self.salon.pk,
            as_of=AS_OF, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_future_appointments_value_csv(self.salon, AS_OF))

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_future", "--salon-id", str(self.salon.pk),
            "--as-of", AS_OF.isoformat(), "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_future_appointments_value_csv(self.salon, AS_OF))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_future", salon_id=self.salon.pk,
            as_of=AS_OF, format="json", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual(
            rows, export_future_appointments_value(self.salon, AS_OF))
        self.assertEqual(
            out.getvalue(),
            json.dumps(export_future_appointments_value(self.salon, AS_OF),
                       indent=2) + "\n")
        # Money stays a string in JSON, never a float.
        self.assertEqual(rows[0]["value"], "0.00")
        self.assertEqual(rows[0]["total"], "0.00")
        self.assertIsInstance(rows[0]["value"], str)

    def test_json_flag_matches_dict_service(self):
        out = io.StringIO()
        call_command(
            "export_future", "--salon-id", str(self.salon.pk),
            "--as-of", AS_OF.isoformat(), "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_future_appointments_value(self.salon, AS_OF))

    def test_json_composes_with_as_of(self):
        later = AS_OF + datetime.timedelta(days=2)
        out = io.StringIO()
        call_command(
            "export_future", salon_id=self.salon.pk,
            as_of=later, format="json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_future_appointments_value(self.salon, later))

    def test_json_output_file_matches_dict_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "future.json")
            call_command(
                "export_future", salon_id=self.salon.pk,
                as_of=AS_OF, format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            json.loads(written),
            export_future_appointments_value(self.salon, AS_OF))
        self.assertEqual(out.getvalue(), "")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_future", salon_id=self.salon.pk,
                as_of=AS_OF, format="xml", stdout=io.StringIO())

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_future", "--salon-id", str(self.salon.pk),
                "--as-of", AS_OF.isoformat(), "--format", "xml",
                stdout=io.StringIO())
