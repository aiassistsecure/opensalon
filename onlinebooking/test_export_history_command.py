"""Tests for the export_history management command.

The command is a thin wrapper around
``onlinebooking.export_history.export_history_csv``: these
tests pin that its stdout and file output match that service
verbatim, that salon/client scoping and the now/limit
arguments forward to the service, and that an unknown salon,
an unknown client, an invalid now, and unwritable output fail
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
from onlinebooking.export_history import export_history_csv
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour=10):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12)


class ExportHistoryCommandTests(TestCase):
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
        self.newer = self._appt(at(-1), client=self.client)
        self.older = self._appt(at(-2), client=self.other_client)

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
        call_command("export_history", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service_salon_wide(self):
        out = self.run_export()
        self.assertEqual(out, export_history_csv(self.salon, None, now=NOW))
        self.assertEqual(
            self.exported_ids(out), [self.newer.pk, self.older.pk])

    def test_stdout_matches_service_for_client(self):
        out = self.run_export(client_id=self.client.pk)
        self.assertEqual(
            out, export_history_csv(self.salon, self.client, now=NOW))
        self.assertEqual(self.exported_ids(out), [self.newer.pk])

    def test_stdout_matches_service_with_string_args(self):
        out = io.StringIO()
        call_command(
            "export_history", "--salon-id", str(self.salon.pk),
            "--client-id", str(self.client.pk),
            "--now", NOW.isoformat(), "--limit", "1", stdout=out)
        self.assertEqual(
            out.getvalue(), export_history_csv(
                self.salon, self.client, now=NOW, limit=1))

    def test_limit_forwards_to_service(self):
        out = self.run_export(limit=1)
        self.assertEqual(
            out, export_history_csv(self.salon, None, now=NOW, limit=1))
        self.assertEqual(self.exported_ids(out), [self.newer.pk])

    def test_salon_scoping_excludes_other_salon(self):
        outsider = Client.objects.create(
            salon=self.other_salon, first_name="Out", last_name="Sider")
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Mallory")
        foreign = self._appt(at(-1, 11), client=outsider, staff=other_staff)
        out = self.run_export()
        self.assertEqual(out, export_history_csv(self.salon, None, now=NOW))
        self.assertNotIn(foreign.pk, self.exported_ids(out))
        out_other = self.run_export(client_id=outsider.pk)
        self.assertEqual(
            out_other, export_history_csv(self.salon, outsider, now=NOW))
        self.assertEqual(self.exported_ids(out_other), [])

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "history.csv")
            out = self.run_export(client_id=self.client.pk, output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(), export_history_csv(
                        self.salon, self.client, now=NOW))

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
            path = os.path.join(tmp, "missing-dir", "history.csv")
            with self.assertRaises(CommandError):
                self.run_export(output=path)
