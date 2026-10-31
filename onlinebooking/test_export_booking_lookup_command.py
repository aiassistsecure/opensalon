"""Tests for the export_booking_lookup management command.

The command is a thin wrapper around
``onlinebooking.lookup_export.export_lookup_csv``: these tests
pin that its stdout and file output match that service verbatim,
that salon/client scoping forwards to the service, and that an
unknown salon, an unknown client, and unwritable output fail
cleanly as ``CommandError``. Fixtures are tiny synthetic
records -- unit logic only.
"""
import csv
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.lookup_export import export_lookup_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour):
    start = NOW + datetime.timedelta(days=day_offset, hours=hour - 12)
    return start


class ExportBookingLookupCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        self.mine = self._appt(at(1, 10), client=self.client)
        self.theirs = self._appt(at(1, 9), client=self.other_client)

    def _appt(self, start, client=None, staff=None, service=None, **kw):
        return Appointment.objects.create(
            client=client or self.client,
            staff_member=staff or self.staff,
            service=service or self.service,
            start=start, end=start + datetime.timedelta(hours=1),
            status="booked", origin="online", **kw)

    def exported_ids(self, text):
        return [int(r["id"]) for r in csv.DictReader(io.StringIO(text))]

    def run_export(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("now", NOW)
        call_command("export_booking_lookup", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service_salon_wide(self):
        out = self.run_export()
        self.assertEqual(out, export_lookup_csv(self.salon, None, now=NOW))
        self.assertIn("Alice", out)

    def test_stdout_matches_service_for_client(self):
        out = self.run_export(client_id=self.client.pk)
        self.assertEqual(
            out, export_lookup_csv(self.salon, self.client, now=NOW))
        self.assertIn(self.mine.pk, self.exported_ids(out))
        self.assertNotIn(self.theirs.pk, self.exported_ids(out))

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            "export_booking_lookup", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--now", NOW.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_lookup_csv(self.salon, self.client, now=NOW))

    def test_salon_scoping_excludes_other_salon(self):
        outsider = Client.objects.create(
            salon=self.other_salon, first_name="Out", last_name="Sider")
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Mallory")
        other_cat = ServiceCategory.objects.create(
            salon=self.other_salon, name="Hair")
        other_service = Service.objects.create(
            category=other_cat, name="Haircut", service_minutes=60)
        foreign = self._appt(
            at(1, 8), client=outsider, staff=other_staff,
            service=other_service)
        # Salon-wide export for this salon never carries the foreign row.
        out = self.run_export()
        self.assertEqual(out, export_lookup_csv(self.salon, None, now=NOW))
        self.assertNotIn(foreign.pk, self.exported_ids(out))
        # A client of another salon scoped to this salon exports nothing.
        out_other = self.run_export(client_id=outsider.pk)
        self.assertEqual(
            out_other, export_lookup_csv(self.salon, outsider, now=NOW))
        self.assertEqual(self.exported_ids(out_other), [])

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "booking_lookup.csv")
            out = self.run_export(client_id=self.client.pk, output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(),
                    export_lookup_csv(self.salon, self.client, now=NOW))

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(salon_id=self.salon.pk + 999)

    def test_unknown_client_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(client_id=self.client.pk + 999)

    def test_invalid_now_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(now="not-a-datetime")

    def test_unwritable_output_raises_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing-dir", "booking_lookup.csv")
            with self.assertRaises(CommandError):
                self.run_export(output=path)
