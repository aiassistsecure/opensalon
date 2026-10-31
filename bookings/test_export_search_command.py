"""Tests for the export_search management command.

The command is a thin wrapper around
``bookings.search_export.export_search_csv``: these tests pin
that its stdout and file output match that service verbatim,
that salon scoping is honoured, and that unknown salons and
unwritable outputs fail cleanly. Fixtures are tiny synthetic
records -- unit logic only.

Note: other apps also define an ``export_search`` command, so
these tests load the bookings command class explicitly via
``load_command_class("bookings", "export_search")`` and pass
that instance to ``call_command`` -- pinning this app's
command, not the global name resolution.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from bookings.models import Appointment
from bookings.search_export import export_search_csv
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(
        day, datetime.time(hour, minute), tzinfo=UTC)


def _cmd():
    return load_command_class("bookings", "export_search")


class ExportSearchCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.alice = Client.objects.create(
            salon=self.salon, first_name="Alice", last_name="Smith")
        self.bob = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Jones")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.alice_appt = Appointment.objects.create(
            client=self.alice, staff_member=self.staff,
            service=self.service, start=at(DAY, 9), end=at(DAY, 10),
            status=Appointment.Status.BOOKED)
        self.bob_appt = Appointment.objects.create(
            client=self.bob, staff_member=self.staff2,
            service=self.service, start=at(DAY, 11), end=at(DAY, 12),
            status=Appointment.Status.CONFIRMED)
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Stylist One")
        other_client = Client.objects.create(
            salon=self.other_salon, first_name="Alice", last_name="Smith")
        Appointment.objects.create(
            client=other_client, staff_member=other_staff,
            service=self.service, start=at(DAY, 10), end=at(DAY, 11))

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_search_csv(self.salon))

    def test_stdout_matches_service_with_filters(self):
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--query", "alice", "--date-from", DAY.isoformat(),
            "--date-to", DAY.isoformat(),
            "--staff-member", str(self.staff.pk),
            "--status", "booked", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_csv(
                self.salon, query="alice", date_from=DAY, date_to=DAY,
                staff_member=self.staff.pk, status="booked"))

    def test_stdout_matches_service_with_kwargs_filters(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, query="bob",
            date_from=DAY, date_to=DAY, staff_member=self.staff2,
            status="confirmed", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_search_csv(
                self.salon, query="bob", date_from=DAY, date_to=DAY,
                staff_member=self.staff2, status="confirmed"))

    def test_salon_scoping(self):
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_search_csv(self.salon))
        self.assertNotIn("Other", out.getvalue())
        # Only this salon's two appointments are exported.
        self.assertEqual(len(out.getvalue().strip().splitlines()), 3)
        other_out = io.StringIO()
        call_command(
            _cmd(), salon_id=self.other_salon.pk,
            stdout=other_out)
        self.assertEqual(
            other_out.getvalue(), export_search_csv(self.other_salon))
        self.assertEqual(
            len(other_out.getvalue().strip().splitlines()), 2)

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "search.csv")
            call_command(
                _cmd(), salon_id=self.salon.pk, query="alice",
                output=path, stdout=out)
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_search_csv(self.salon, query="alice"))
        self.assertEqual(out.getvalue(), "")

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                _cmd(), salon_id=self.salon.pk + 1000,
                stdout=io.StringIO())

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "search.csv")
            with self.assertRaises(CommandError):
                call_command(
                    _cmd(), salon_id=self.salon.pk,
                    output=path, stdout=io.StringIO())
