"""NEDB-safe --dry-run regression tests for team commands.

set_shift_override (set AND --clear paths),
mark_notifications_seen, and notify_staff used to preview by
calling the real writer inside ``transaction.atomic()`` and
relying on ``set_rollback(True)`` -- a no-op on NEDB, so a
dry run wrote for real there. These tests pin the converted
mechanism: a dry run never calls the writer at all (mocked
writers assert this, so the tests fail on the old mechanism
even on SQLite, where rollback masked it) and leaves every
row exactly as it was. Fixtures are tiny synthetic records.
"""
import datetime
import io
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import ShiftOverride, StaffMember, StaffNotification
from team.notifications import notify_staff, validate_notify_staff
from team.shift_overrides import validate_set_shift_override

SAT = datetime.date(2026, 10, 31)
T9 = datetime.time(9, 0)
T17 = datetime.time(17, 0)


def _run(name, **kwargs):
    out = io.StringIO()
    call_command(name, stdout=out, **kwargs)
    return out.getvalue()


class Fixture(TestCase):
    def setUp(self):
        salon = Salon.objects.create(name="Dry Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=salon, name="Hair")
        service = Service.objects.create(
            category=category, name="Cut", service_minutes=60)
        self.member = StaffMember.objects.create(
            salon=salon, display_name="Dana")
        client = Client.objects.create(
            salon=salon, first_name="Robin", last_name="Guest")
        start = timezone.now().replace(
            hour=10, minute=0, second=0, microsecond=0)
        self.appt = Appointment.objects.create(
            client=client, staff_member=self.member, service=service,
            service_name="Cut", start=start,
            end=start + datetime.timedelta(hours=1))


class SetShiftOverrideDryRunTests(Fixture):
    def test_dry_run_set_never_calls_writer_and_writes_nothing(self):
        with mock.patch(
                "team.management.commands.set_shift_override"
                ".set_shift_override") as writer:
            out = _run("set_shift_override",
                       staff_member_id=self.member.pk, date=SAT,
                       start="10:00", end="14:00", dry_run=True)
        writer.assert_not_called()
        self.assertIn("Dry run: would set", out)
        self.assertIn("10:00", out)
        self.assertEqual(ShiftOverride.objects.count(), 0)

    def test_dry_run_clear_never_calls_writer_and_deletes_nothing(self):
        ShiftOverride.objects.create(
            staff_member=self.member, date=SAT, is_off=True)
        with mock.patch(
                "team.management.commands.set_shift_override"
                ".clear_shift_override") as writer:
            out = _run("set_shift_override",
                       staff_member_id=self.member.pk, date=SAT,
                       clear=True, dry_run=True)
        writer.assert_not_called()
        self.assertIn("Dry run: would clear", out)
        self.assertIn("an override exists", out)
        # The regression: dry-run --clear must NOT delete.
        self.assertEqual(ShiftOverride.objects.count(), 1)
        self.assertTrue(ShiftOverride.objects.get().is_off)

    def test_dry_run_clear_with_no_override_reports_none(self):
        out = _run("set_shift_override", staff_member_id=self.member.pk,
                   date=SAT, clear=True, dry_run=True)
        self.assertIn("no override exists", out)
        self.assertEqual(ShiftOverride.objects.count(), 0)

    def test_dry_run_invalid_shape_is_error_and_writes_nothing(self):
        with self.assertRaises(CommandError):
            _run("set_shift_override", staff_member_id=self.member.pk,
                 date=SAT, start="14:00", end="10:00", dry_run=True)
        self.assertEqual(ShiftOverride.objects.count(), 0)

    def test_validate_set_shift_override_writes_nothing(self):
        self.assertEqual(
            validate_set_shift_override(
                self.member, SAT, start_time=T9, end_time=T17),
            (SAT, False, T9, T17))
        self.assertEqual(
            validate_set_shift_override(self.member, SAT, is_off=True),
            (SAT, True, None, None))
        with self.assertRaises(ValidationError):
            validate_set_shift_override(self.member, SAT)
        self.assertEqual(ShiftOverride.objects.count(), 0)


class NotifyStaffDryRunTests(Fixture):
    def test_dry_run_never_calls_writer_and_writes_nothing(self):
        with mock.patch(
                "team.management.commands.notify_staff"
                ".notify_staff") as writer:
            out = _run("notify_staff", staff_member_id=self.member.pk,
                       appointment_id=self.appt.pk, dry_run=True)
        writer.assert_not_called()
        self.assertIn("Dry run: would create", out)
        self.assertIn("kind=arrived", out)
        self.assertEqual(StaffNotification.objects.count(), 0)

    def test_dry_run_blank_kind_is_error_and_writes_nothing(self):
        with self.assertRaises(CommandError):
            _run("notify_staff", staff_member_id=self.member.pk,
                 appointment_id=self.appt.pk, kind="  ", dry_run=True)
        self.assertEqual(StaffNotification.objects.count(), 0)

    def test_validate_notify_staff_writes_nothing(self):
        self.assertEqual(
            validate_notify_staff(self.member, self.appt, " arrived "),
            "arrived")
        with self.assertRaises(ValidationError):
            validate_notify_staff(self.member, self.appt, kind="")
        with self.assertRaises(ValidationError):
            validate_notify_staff(None, self.appt)
        self.assertEqual(StaffNotification.objects.count(), 0)


class MarkNotificationsSeenDryRunTests(Fixture):
    def test_dry_run_never_calls_writer_and_stamps_nothing(self):
        notify_staff(self.member, self.appt)
        notify_staff(self.member, self.appt)
        with mock.patch(
                "team.management.commands.mark_notifications_seen"
                ".mark_seen") as writer:
            out = _run("mark_notifications_seen",
                       staff_member_id=self.member.pk, dry_run=True)
        writer.assert_not_called()
        self.assertIn("Dry run: would mark 2", out)
        self.assertEqual(
            StaffNotification.objects.filter(
                seen_at__isnull=True).count(), 2)

    def test_dry_run_count_matches_real_run(self):
        notify_staff(self.member, self.appt)
        _run("mark_notifications_seen", staff_member_id=self.member.pk,
             dry_run=True)
        out = _run("mark_notifications_seen",
                   staff_member_id=self.member.pk)
        self.assertIn("Marked 1", out)
        self.assertEqual(
            StaffNotification.objects.filter(
                seen_at__isnull=True).count(), 0)
