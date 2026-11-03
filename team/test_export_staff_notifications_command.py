"""Tests for export_staff_notifications: stdout/file == service."""
import datetime
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember, StaffNotification
from team.notification_export import export_staff_notifications_csv

T1 = datetime.datetime(2026, 1, 1, 15, 0, tzinfo=datetime.timezone.utc)


class ExportStaffNotificationsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Inbox Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Cut", service_minutes=60)
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana")
        client = Client.objects.create(
            salon=self.salon, first_name="Robin", last_name="Guest")
        start = timezone.now().replace(hour=10, minute=0, second=0,
                                       microsecond=0)
        appt = Appointment.objects.create(
            client=client, staff_member=self.staff, service=service,
            service_name="Cut", start=start,
            end=start + datetime.timedelta(hours=1))
        note = StaffNotification.objects.create(
            staff_member=self.staff, appointment=appt, kind="arrived")
        StaffNotification.objects.filter(pk=note.pk).update(created_at=T1)

    def test_stdout_matches_service_output(self):
        out = io.StringIO()
        call_command("export_staff_notifications",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_staff_notifications_csv(self.salon))
        self.assertIn("Dana", out.getvalue())
        self.assertIn(T1.isoformat(), out.getvalue())

    def test_output_file_matches_service_output(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as fh:
            path = fh.name
        out = io.StringIO()
        call_command("export_staff_notifications",
                     salon_id=self.salon.id, output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_staff_notifications_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_header_only(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        out = io.StringIO()
        call_command("export_staff_notifications",
                     salon_id=empty.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_staff_notifications_csv(empty))

    def test_unknown_salon_required_id_and_unwritable(self):
        with self.assertRaises(CommandError):
            call_command("export_staff_notifications",
                         salon_id=999999, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_staff_notifications", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_staff_notifications",
                         salon_id=self.salon.id,
                         output="/nonexistent-dir/out.csv",
                         stdout=io.StringIO())
