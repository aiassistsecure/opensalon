"""Tests for the import_appointments management command.

Fixtures are tiny hand-written JSON documents in the verbatim extract
shape — unit logic only, no real salon data, synthetic ids only.
"""
import io
import json
import os
import tempfile
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

FIXTURE = [
    {"appointmentId": "appt-1", "clientId": "cli-1", "staffId": "stf-1",
     "serviceId": "svc-1", "appointmentDate": "2026-10-03",
     "startTime": "09:00:00.000", "endTime": "09:45:00.000",
     "price": 45.0, "state": "PAID", "deleted": False},
    {"appointmentId": "appt-2", "clientId": "cli-1", "staffId": "stf-1",
     "serviceId": "svc-1", "appointmentDate": "2026-10-03",
     "startTime": "10:00:00.000", "endTime": "10:30:00.000",
     "price": 30.0, "state": "CHECKED_IN", "deleted": False},
    {"appointmentId": "appt-3", "clientId": "cli-1", "staffId": "stf-1",
     "serviceId": "svc-1", "appointmentDate": "2026-10-04",
     "startTime": "11:00:00.000", "endTime": "11:30:00.000",
     "price": 30.0, "state": "BOOKED", "deleted": False},
    {"appointmentId": "appt-4", "clientId": "cli-x", "staffId": "stf-1",
     "serviceId": "svc-1", "appointmentDate": "2026-10-04",
     "startTime": "12:00:00.000", "endTime": "12:30:00.000",
     "state": "BOOKED", "deleted": False},  # unresolved client
    {"appointmentId": "appt-5", "clientId": "cli-1", "staffId": "stf-x",
     "serviceId": "svc-1", "appointmentDate": "2026-10-04",
     "startTime": "12:00:00.000", "endTime": "12:30:00.000",
     "state": "BOOKED", "deleted": False},  # unresolved staff
    {"appointmentId": "appt-6", "clientId": "cli-1", "staffId": "stf-1",
     "serviceId": "svc-x", "appointmentDate": "2026-10-04",
     "startTime": "12:00:00.000", "endTime": "12:30:00.000",
     "state": "BOOKED", "deleted": False},  # unresolved service
    {"appointmentId": "appt-7", "clientId": "cli-1", "staffId": "stf-1",
     "serviceId": "svc-1", "appointmentDate": "2026-10-04",
     "startTime": "12:00:00.000", "endTime": "12:30:00.000",
     "state": "PAID", "deleted": True},  # deleted: skipped
    {"clientId": "cli-1", "staffId": "stf-1", "serviceId": "svc-1",
     "appointmentDate": "2026-10-04", "startTime": "12:00:00.000",
     "endTime": "12:30:00.000", "state": "BOOKED"},  # no id: skipped
]


def _write(payload, name="appointments.json"):
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


class ImportAppointmentsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="My Salon", timezone="America/New_York")
        self.client = Client.objects.create(
            salon=self.salon, external_id="cli-1",
            first_name="Test", last_name="Example")
        self.staff = StaffMember.objects.create(
            salon=self.salon, external_id="stf-1",
            display_name="Stylist One")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts")
        self.service = Service.objects.create(
            category=category, external_id="svc-1", name="Haircut",
            service_minutes=45)

    def run_import(self, payload=FIXTURE, path=None, **kwargs):
        out = io.StringIO()
        call_command("import_appointments", path or _write(payload),
                     stdout=out, **kwargs)
        return out.getvalue()

    def test_imports_resolves_and_combines_datetimes(self):
        out = self.run_import()
        self.assertIn('"created": 3', out)
        self.assertIn('"unresolved_client": 1', out)
        self.assertIn('"unresolved_staff": 1', out)
        self.assertIn('"unresolved_service": 1', out)
        self.assertIn('"skipped": 2', out)
        self.assertIn('"date_min": "2026-10-03"', out)
        appt = Appointment.objects.get(external_id="appt-1")
        self.assertEqual(appt.client, self.client)
        self.assertEqual(appt.staff_member, self.staff)
        self.assertEqual(appt.service, self.service)
        ny = ZoneInfo("America/New_York")
        local = appt.start.astimezone(ny)
        self.assertEqual(
            (local.year, local.month, local.day, local.hour, local.minute),
            (2026, 10, 3, 9, 0))
        end_local = appt.end.astimezone(ny)
        self.assertEqual((end_local.hour, end_local.minute), (9, 45))

    def test_state_mapping(self):
        self.run_import()
        self.assertEqual(Appointment.objects.get(
            external_id="appt-1").status, Appointment.Status.COMPLETED)
        self.assertEqual(Appointment.objects.get(
            external_id="appt-2").status, Appointment.Status.ARRIVED)
        self.assertEqual(Appointment.objects.get(
            external_id="appt-3").status, Appointment.Status.BOOKED)

    def test_directory_input_reads_every_file(self):
        directory = tempfile.mkdtemp()
        for name, rows in (("2026-10.json", FIXTURE[:1]),
                           ("2026-11.json", FIXTURE[1:3])):
            with open(os.path.join(directory, name), "w") as fh:
                json.dump(rows, fh)
        out = self.run_import(path=directory)
        self.assertIn('"created": 3', out)
        self.assertEqual(Appointment.objects.count(), 3)

    def test_rerun_skips_unchanged_and_updates_changed_in_place(self):
        self.run_import()
        changed = json.loads(json.dumps(FIXTURE))
        changed[0]["state"] = "BOOKED"
        out = self.run_import(payload=changed)
        self.assertIn('"created": 0', out)
        self.assertIn('"updated": 1', out)
        self.assertIn('"unchanged": 2', out)
        self.assertEqual(Appointment.objects.count(), 3)
        self.assertEqual(Appointment.objects.get(
            external_id="appt-1").status, Appointment.Status.BOOKED)

    def test_rerun_without_changes_is_all_unchanged(self):
        self.run_import()
        out = self.run_import()
        self.assertIn('"created": 0', out)
        self.assertIn('"updated": 0', out)
        self.assertIn('"unchanged": 3', out)
        self.assertEqual(Appointment.objects.count(), 3)

    def test_unresolved_service_with_name_imports_as_snapshot(self):
        payload = [{"appointmentId": "appt-snap", "clientId": "cli-1",
                    "staffId": "stf-1", "serviceId": "svc-missing",
                    "serviceName": "Legacy Treatment",
                    "appointmentDate": "2026-10-03",
                    "startTime": "13:00:00", "endTime": "13:45:00",
                    "state": "BOOKED", "deleted": False}]
        out = self.run_import(payload=payload)
        self.assertIn('"created": 1', out)
        self.assertIn('"unresolved_service": 1', out)
        self.assertIn('"imported_with_service_snapshot": 1', out)
        appt = Appointment.objects.get(external_id="appt-snap")
        self.assertIsNone(appt.service)
        self.assertEqual(appt.service_name, "Legacy Treatment")

    def test_unresolved_service_without_name_still_skips(self):
        payload = [{"appointmentId": "appt-noname", "clientId": "cli-1",
                    "staffId": "stf-1", "serviceId": "svc-missing",
                    "appointmentDate": "2026-10-03",
                    "startTime": "13:00:00", "endTime": "13:45:00",
                    "state": "BOOKED", "deleted": False}]
        out = self.run_import(payload=payload)
        self.assertIn('"created": 0', out)
        self.assertIn('"unresolved_service": 1', out)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_resolved_service_snapshots_its_name(self):
        self.run_import(payload=FIXTURE[:1])
        appt = Appointment.objects.get(external_id="appt-1")
        self.assertEqual(appt.service, self.service)
        self.assertEqual(appt.service_name, "Haircut")

    def test_missing_file_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("import_appointments", "/nonexistent/x.json")

    # TZ-M2: wall times are salon-local, stored as correct UTC instant.

    def test_wall_time_stored_as_exact_utc_instant_edt(self):
        # 2026-10-03 is EDT (UTC-4) in America/New_York.
        self.run_import(payload=FIXTURE[:1])
        appt = Appointment.objects.get(external_id="appt-1")
        self.assertEqual(appt.start, datetime(
            2026, 10, 3, 13, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(appt.end, datetime(
            2026, 10, 3, 13, 45, tzinfo=dt_timezone.utc))
        local = appt.start.astimezone(ZoneInfo("America/New_York"))
        self.assertEqual((local.hour, local.minute), (9, 0))

    def test_wall_time_stored_as_exact_utc_instant_est(self):
        # 2026-01-15 is EST (UTC-5) in America/New_York.
        payload = [{"appointmentId": "appt-winter", "clientId": "cli-1",
                    "staffId": "stf-1", "serviceId": "svc-1",
                    "appointmentDate": "2026-01-15",
                    "startTime": "09:00:00", "endTime": "09:45:00",
                    "state": "BOOKED", "deleted": False}]
        self.run_import(payload=payload)
        appt = Appointment.objects.get(external_id="appt-winter")
        self.assertEqual(appt.start, datetime(
            2026, 1, 15, 14, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(appt.end, datetime(
            2026, 1, 15, 14, 45, tzinfo=dt_timezone.utc))

    def test_utc_salon_behaviour_unchanged(self):
        self.salon.timezone = "UTC"
        self.salon.save(update_fields=["timezone"])
        self.run_import(payload=FIXTURE[:1])
        appt = Appointment.objects.get(external_id="appt-1")
        self.assertEqual(appt.start, datetime(
            2026, 10, 3, 9, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(appt.end, datetime(
            2026, 10, 3, 9, 45, tzinfo=dt_timezone.utc))

    def test_timezone_option_sets_existing_salon_timezone(self):
        self.salon.timezone = "UTC"
        self.salon.save(update_fields=["timezone"])
        self.run_import(payload=FIXTURE[:1], timezone="America/New_York")
        self.salon.refresh_from_db()
        self.assertEqual(self.salon.timezone, "America/New_York")
        appt = Appointment.objects.get(external_id="appt-1")
        self.assertEqual(appt.start, datetime(
            2026, 10, 3, 13, 0, tzinfo=dt_timezone.utc))

    def test_timezone_option_creates_new_salon_with_timezone(self):
        out = io.StringIO()
        call_command("import_appointments", _write(FIXTURE[:1]),
                     salon="Synthetic Salon", timezone="America/New_York",
                     stdout=out)
        salon = Salon.objects.get(name="Synthetic Salon")
        self.assertEqual(salon.timezone, "America/New_York")
        # No clients/staff scoped to the new salon: nothing imported.
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertIn('"created": 0', out.getvalue())

    def test_timezone_option_invalid_raises_and_leaves_salon(self):
        with self.assertRaises(CommandError):
            self.run_import(payload=FIXTURE[:1], timezone="Not/AZone")
        self.salon.refresh_from_db()
        self.assertEqual(self.salon.timezone, "America/New_York")
        self.assertEqual(Appointment.objects.count(), 0)
