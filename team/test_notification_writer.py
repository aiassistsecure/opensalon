"""Tests for the StaffNotification writer service + commands.

The writer half of team.notifications: notify_staff creates
the arrival ping in webui's exact shape, mark_seen stamps
only that member's unseen pings. Commands notify_staff and
mark_notifications_seen are thin wrappers, with --dry-run
previewing without writing anything. Fixtures are
tiny synthetic records -- unit logic only.
"""
import datetime
import io

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember, StaffNotification
from team.notifications import mark_seen, notify_staff


def _notify_cmd(**kwargs):
    out = io.StringIO()
    call_command("notify_staff", stdout=out, **kwargs)
    return out.getvalue()


def _seen_cmd(**kwargs):
    out = io.StringIO()
    call_command("mark_notifications_seen", stdout=out, **kwargs)
    return out.getvalue()


class WriterFixture(TestCase):
    def setUp(self):
        salon = Salon.objects.create(name="Ping Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Cut", service_minutes=60)
        self.member = StaffMember.objects.create(
            salon=salon, display_name="Dana")
        self.other = StaffMember.objects.create(
            salon=salon, display_name="Eva")
        client = Client.objects.create(
            salon=salon, first_name="Robin", last_name="Guest")
        start = timezone.now().replace(
            hour=10, minute=0, second=0, microsecond=0)
        self.appt = Appointment.objects.create(
            client=client, staff_member=self.member, service=service,
            service_name="Cut", start=start,
            end=start + datetime.timedelta(hours=1))


class NotifyStaffServiceTests(WriterFixture):
    def test_creates_arrival_ping_in_webui_shape(self):
        note = notify_staff(self.member, self.appt)
        self.assertEqual(note.staff_member, self.member)
        self.assertEqual(note.appointment, self.appt)
        self.assertEqual(note.kind, "arrived")
        self.assertIsNone(note.seen_at)
        self.assertEqual(StaffNotification.objects.count(), 1)

    def test_explicit_kind_and_repeat_pings(self):
        notify_staff(self.member, self.appt, kind="arrived")
        note = notify_staff(self.member, self.appt, kind="arrived")
        self.assertEqual(note.kind, "arrived")
        self.assertEqual(StaffNotification.objects.count(), 2)

    def test_blank_kind_writes_nothing(self):
        with self.assertRaises(ValidationError):
            notify_staff(self.member, self.appt, kind="  ")
        with self.assertRaises(ValidationError):
            notify_staff(None, self.appt)
        with self.assertRaises(ValidationError):
            notify_staff(self.member, None)
        self.assertEqual(StaffNotification.objects.count(), 0)


class MarkSeenServiceTests(WriterFixture):
    def test_stamps_only_members_unseen_and_returns_count(self):
        notify_staff(self.member, self.appt)
        notify_staff(self.member, self.appt)
        notify_staff(self.other, self.appt)
        already = notify_staff(self.member, self.appt)
        stamp = timezone.now() - datetime.timedelta(hours=1)
        StaffNotification.objects.filter(pk=already.pk).update(
            seen_at=stamp)
        self.assertEqual(mark_seen(self.member), 2)
        mine = StaffNotification.objects.filter(staff_member=self.member)
        self.assertTrue(all(n.seen_at is not None for n in mine))
        already.refresh_from_db()
        self.assertEqual(already.seen_at, stamp)
        self.assertIsNone(
            StaffNotification.objects.get(
                staff_member=self.other).seen_at)
        self.assertEqual(mark_seen(self.member), 0)


class NotifyStaffCommandTests(WriterFixture):
    def test_command_creates_ping(self):
        out = _notify_cmd(staff_member_id=self.member.pk,
                          appointment_id=self.appt.pk)
        self.assertIn("kind=arrived", out)
        note = StaffNotification.objects.get()
        self.assertEqual((note.staff_member, note.appointment),
                         (self.member, self.appt))

    def test_command_via_cli_with_kind(self):
        out = io.StringIO()
        call_command("notify_staff", "--staff-member-id",
                     str(self.member.pk), "--appointment-id",
                     str(self.appt.pk), "--kind", "arrived",
                     stdout=out)
        self.assertIn("arrived", out.getvalue())
        self.assertEqual(StaffNotification.objects.count(), 1)

    def test_dry_run_writes_nothing(self):
        out = _notify_cmd(staff_member_id=self.member.pk,
                          appointment_id=self.appt.pk, dry_run=True)
        self.assertIn("Dry run: would create", out)
        self.assertIn("kind=arrived", out)
        self.assertEqual(StaffNotification.objects.count(), 0)

    def test_unknown_ids_are_errors_and_write_nothing(self):
        with self.assertRaises(CommandError):
            _notify_cmd(staff_member_id=self.member.pk + 1000,
                        appointment_id=self.appt.pk)
        with self.assertRaises(CommandError):
            _notify_cmd(staff_member_id=self.member.pk,
                        appointment_id=self.appt.pk + 1000)
        self.assertEqual(StaffNotification.objects.count(), 0)


class MarkSeenCommandTests(WriterFixture):
    def test_command_marks_seen_and_reports_count(self):
        notify_staff(self.member, self.appt)
        notify_staff(self.member, self.appt)
        out = _seen_cmd(staff_member_id=self.member.pk)
        self.assertIn("Marked 2", out)
        self.assertEqual(
            StaffNotification.objects.filter(
                seen_at__isnull=True).count(), 0)

    def test_dry_run_reports_count_and_writes_nothing(self):
        notify_staff(self.member, self.appt)
        notify_staff(self.member, self.appt)
        out = _seen_cmd(staff_member_id=self.member.pk, dry_run=True)
        self.assertIn("Dry run: would mark 2", out)
        self.assertEqual(
            StaffNotification.objects.filter(
                seen_at__isnull=True).count(), 2)

    def test_unknown_staff_is_error(self):
        with self.assertRaises(CommandError):
            _seen_cmd(staff_member_id=self.member.pk + 1000)
