"""Tests for the export_appointments management command.

The command is a thin wrapper around
``bookings.export.export_appointments``: these tests pin that
its stdout and file output are that service's list serialized
verbatim as JSON and that unknown salons, bad dates, service
errors, and unwritable outputs fail cleanly. Fixtures are tiny
synthetic records -- unit logic only.
"""
import csv
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.export import EXPORT_FIELDNAMES, export_appointments
from bookings.models import Appointment
from clients.models import Client
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc
COMMAND_SERVICE = "bookings.management.commands.export_appointments.export_appointments"


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


def expected_text(*args, **kwargs):
    return json.dumps(export_appointments(*args, **kwargs), indent=2) + "\n"


class ExportAppointmentsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One", staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"))
        self.booked = self._appt(DAY, 9, status=Appointment.Status.CONFIRMED)
        self.cancelled = self._appt(DAY, 11, status=Appointment.Status.CANCELLED)
        self.next_day = self._appt(NEXT, 9)

    def _appt(self, day, hour, **kw):
        kw.setdefault("client", self.client)
        kw.setdefault("staff_member", self.staff)
        kw.setdefault("service", self.service)
        return Appointment.objects.create(
            start=at(day, hour), end=at(day, hour + 1), **kw)

    def test_stdout_matches_service_verbatim_json(self):
        out = io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(), expected_text(self.salon, DAY, DAY))
        self.assertEqual(
            [row["id"] for row in json.loads(out.getvalue())],
            [self.booked.pk, self.cancelled.pk])

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_appointments", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--date-to", NEXT.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(), expected_text(self.salon, DAY, NEXT))

    def test_output_file_matches_service_and_stdout_stays_empty(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "appointments.json")
            call_command(
                "export_appointments", salon_id=self.salon.pk,
                date_from=DAY, date_to=DAY, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(written, expected_text(self.salon, DAY, DAY))
        self.assertEqual(out.getvalue(), "")

    def test_omitted_date_to_is_single_day(self):
        out = io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, stdout=out)
        self.assertEqual(out.getvalue(), expected_text(self.salon, DAY, None))
        self.assertNotIn(self.next_day.pk,
                         [row["id"] for row in json.loads(out.getvalue())])

    def test_cancelled_included_by_default_excluded_on_request(self):
        out = io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, date_to=DAY, stdout=out)
        self.assertIn(self.cancelled.pk,
                      [row["id"] for row in json.loads(out.getvalue())])
        out = io.StringIO()
        call_command(
            "export_appointments", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--date-to", DAY.isoformat(),
            "--no-include-cancelled", stdout=out)
        self.assertEqual(
            out.getvalue(),
            expected_text(self.salon, DAY, DAY, include_cancelled=False))
        self.assertNotIn(self.cancelled.pk,
                         [row["id"] for row in json.loads(out.getvalue())])
        out = io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, date_to=DAY, include_cancelled=False, stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_appointments(self.salon, DAY, DAY, include_cancelled=False))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_appointments", salon_id=self.salon.pk + 1000,
                date_from=DAY, stdout=io.StringIO())

    def test_missing_date_from_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_appointments", salon_id=self.salon.pk,
                stdout=io.StringIO())

    def test_bad_date_from_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_appointments", "--salon-id", str(self.salon.pk),
                "--date-from", "not-a-date", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_appointments", salon_id=self.salon.pk,
                date_from="not-a-date", stdout=io.StringIO())

    def test_bad_date_to_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_appointments", "--salon-id", str(self.salon.pk),
                "--date-from", DAY.isoformat(), "--date-to", "not-a-date",
                stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command(
                "export_appointments", salon_id=self.salon.pk,
                date_from=DAY, date_to="not-a-date", stdout=io.StringIO())

    def test_service_error_raises_command_error(self):
        with mock.patch(COMMAND_SERVICE, side_effect=ValueError("boom")):
            with self.assertRaises(CommandError):
                call_command(
                    "export_appointments", salon_id=self.salon.pk,
                    date_from=DAY, stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "appointments.json")
            with self.assertRaises(CommandError):
                call_command(
                    "export_appointments", salon_id=self.salon.pk,
                    date_from=DAY, date_to=DAY, output=path,
                    stdout=io.StringIO())


def expected_csv_text(rows):
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=EXPORT_FIELDNAMES, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({
            key: (json.dumps(row.get(key)) if isinstance(
                row.get(key), (dict, list, tuple, set)) else row.get(key))
            for key in EXPORT_FIELDNAMES})
    return buffer.getvalue()


class ExportAppointmentsFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One", staff_level=self.level)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"))
        self.booked = Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=at(DAY, 9), end=at(DAY, 10),
            status=Appointment.Status.CONFIRMED)
        self.cancelled = Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=self.service,
            start=at(DAY, 11), end=at(DAY, 12),
            status=Appointment.Status.CANCELLED)

    def _rows(self, **kwargs):
        return export_appointments(self.salon, DAY, DAY, **kwargs)

    def test_default_format_is_byte_exact_json(self):
        out = io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, date_to=DAY, stdout=out)
        self.assertEqual(out.getvalue(), expected_text(self.salon, DAY, DAY))

    def test_explicit_json_matches_default(self):
        default_out, json_out = io.StringIO(), io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, date_to=DAY, stdout=default_out)
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, date_to=DAY, format="json", stdout=json_out)
        self.assertEqual(json_out.getvalue(), default_out.getvalue())
        self.assertEqual(
            json_out.getvalue(), expected_text(self.salon, DAY, DAY))

    def test_csv_matches_service_rows(self):
        out = io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, date_to=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(), expected_csv_text(self._rows()))
        parsed = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(
            [int(row["id"]) for row in parsed],
            [self.booked.pk, self.cancelled.pk])
        self.assertEqual(parsed[0]["price"], "85.00")

    def test_csv_header_and_field_order(self):
        out = io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, date_to=DAY, format="csv", stdout=out)
        header = out.getvalue().splitlines()[0]
        self.assertEqual(header, ",".join(EXPORT_FIELDNAMES))
        self.assertEqual(
            list(csv.DictReader(io.StringIO(out.getvalue())).fieldnames),
            EXPORT_FIELDNAMES)

    def test_csv_via_cli_flags(self):
        out = io.StringIO()
        call_command(
            "export_appointments", "--salon-id", str(self.salon.pk),
            "--date-from", DAY.isoformat(), "--date-to", DAY.isoformat(),
            "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), expected_csv_text(self._rows()))

    def test_csv_output_file_matches_stdout_and_stdout_stays_empty(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "appointments.csv")
            call_command(
                "export_appointments", salon_id=self.salon.pk,
                date_from=DAY, date_to=DAY, format="csv", output=path,
                stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(written, expected_csv_text(self._rows()))
        self.assertEqual(out.getvalue(), "")

    def test_csv_empty_result_is_header_only(self):
        empty_day = DAY + datetime.timedelta(days=30)
        out = io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=empty_day, date_to=empty_day, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(), ",".join(EXPORT_FIELDNAMES) + "\n")

    def test_csv_nested_values_are_json_encoded_cells(self):
        row = {key: None for key in EXPORT_FIELDNAMES}
        row.update({
            "id": 7, "service_name": {"name": "Haircut", "tags": ["a", "b"]}})
        with mock.patch(COMMAND_SERVICE, return_value=[row]):
            out = io.StringIO()
            call_command(
                "export_appointments", salon_id=self.salon.pk,
                date_from=DAY, date_to=DAY, format="csv", stdout=out)
        parsed = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(
            json.loads(parsed[0]["service_name"]),
            {"name": "Haircut", "tags": ["a", "b"]})

    def test_csv_new_fields_round_trip(self):
        Appointment.objects.filter(pk=self.booked.pk).update(
            external_id="ext-csv-1", origin="online",
            price_override=Decimal("70.50"),
            payload={"price": "999", "tags": ["a"]})
        out = io.StringIO()
        call_command(
            "export_appointments", salon_id=self.salon.pk,
            date_from=DAY, date_to=DAY, format="csv", stdout=out)
        parsed = {int(r["id"]): r
                  for r in csv.DictReader(io.StringIO(out.getvalue()))}
        row = parsed[self.booked.pk]
        self.assertEqual(row["external_id"], "ext-csv-1")
        self.assertEqual(row["origin"], "online")
        self.assertEqual(row["price_override"], "70.50")
        self.assertEqual(json.loads(row["payload"]),
                         {"price": "999", "tags": ["a"]})
        self.assertTrue(row["created_at"])
        self.assertTrue(row["updated_at"])

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_appointments", salon_id=self.salon.pk,
                date_from=DAY, date_to=DAY, format="xml",
                stdout=io.StringIO())

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_appointments", "--salon-id", str(self.salon.pk),
                "--date-from", DAY.isoformat(), "--format", "xml",
                stdout=io.StringIO())
