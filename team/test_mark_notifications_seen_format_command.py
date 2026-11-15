"""Tests for --format text|json on mark_notifications_seen.

Mirrors the sibling format tests (copy_member_services):
default text output is byte-identical, explicit text matches,
json prints exactly one object carrying the same facts, and
an invalid format raises CommandError. Fixtures are tiny
synthetic records.
"""
import datetime
import io
import json
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember, StaffNotification
from team.notifications import notify_staff


def _run(name, **kwargs):
    out = io.StringIO()
    call_command(name, stdout=out, **kwargs)
    return out.getvalue()


class MarkNotificationsSeenFormatTests(TestCase):
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
        notify_staff(self.member, self.appt)
        notify_staff(self.member, self.appt)
        notify_staff(self.other, self.appt)

    def _expected_text(self, dry_run=False):
        if dry_run:
            return (f"Dry run: would mark 2 notification(s) seen for "
                    f"staff_member_id={self.member.pk} "
                    f"-- no notification marked seen.\n")
        return (f"Marked 2 notification(s) seen for {self.member} "
                f"staff_member_id={self.member.pk}.\n")

    def test_default_text_output_unchanged(self):
        out = _run("mark_notifications_seen",
                   staff_member_id=self.member.pk)
        self.assertEqual(out, self._expected_text())
        self.assertEqual(
            StaffNotification.objects.filter(
                staff_member=self.member, seen_at__isnull=True).count(), 0)
        self.assertEqual(
            StaffNotification.objects.filter(
                staff_member=self.other, seen_at__isnull=True).count(), 1)

    def test_explicit_text_matches_default(self):
        out = _run("mark_notifications_seen",
                   staff_member_id=self.member.pk, format="text")
        self.assertEqual(out, self._expected_text())

    def test_explicit_text_dry_run_matches_default(self):
        out = _run("mark_notifications_seen",
                   staff_member_id=self.member.pk, dry_run=True,
                   format="text")
        self.assertEqual(out, self._expected_text(dry_run=True))
        self.assertEqual(
            StaffNotification.objects.filter(
                seen_at__isnull=True).count(), 3)

    def test_json_parses_as_one_object_with_correct_values(self):
        out = _run("mark_notifications_seen",
                   staff_member_id=self.member.pk, format="json")
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertNotIn("Marked", out)
        self.assertEqual(json.loads(out), {
            "staff_member_id": self.member.pk,
            "marked_seen": 2,
            "dry_run": False,
        })
        self.assertEqual(
            StaffNotification.objects.filter(
                staff_member=self.member, seen_at__isnull=True).count(), 0)
        self.assertEqual(
            StaffNotification.objects.filter(
                staff_member=self.other, seen_at__isnull=True).count(), 1)

    def test_json_dry_run_never_calls_writer(self):
        with mock.patch(
                "team.management.commands.mark_notifications_seen"
                ".mark_seen") as writer:
            out = _run("mark_notifications_seen",
                       staff_member_id=self.member.pk, dry_run=True,
                       format="json")
        writer.assert_not_called()
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertEqual(json.loads(out), {
            "staff_member_id": self.member.pk,
            "marked_seen": 2,
            "dry_run": True,
        })
        self.assertEqual(
            StaffNotification.objects.filter(
                seen_at__isnull=True).count(), 3)

    def test_json_via_cli(self):
        out = io.StringIO()
        call_command(
            "mark_notifications_seen", "--staff-member-id",
            str(self.member.pk), "--format", "json", stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["staff_member_id"], self.member.pk)
        self.assertEqual(data["marked_seen"], 2)
        self.assertFalse(data["dry_run"])

    def test_invalid_format_rejected(self):
        with self.assertRaises(CommandError):
            _run("mark_notifications_seen",
                 staff_member_id=self.member.pk, format="bogus")
        self.assertEqual(
            StaffNotification.objects.filter(
                staff_member=self.member, seen_at__isnull=True).count(), 2)
        with self.assertRaises(CommandError):
            _run("mark_notifications_seen", staff_member_id=999999,
                 format="json")
