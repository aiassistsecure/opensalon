"""Tests for the export_appointments management command.

The command is a thin wrapper around
``bookings.export.export_appointments``: these tests pin that
its stdout and file output are that service's list serialized
verbatim as JSON and that unknown salons, bad dates, service
errors, and unwritable outputs fail cleanly. Fixtures are tiny
synthetic records -- unit logic only.
"""
import datetime
import io
import json
import os
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.export import export_appointments
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
