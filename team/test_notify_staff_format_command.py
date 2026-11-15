"""Tests for --format text|json on notify_staff.

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


def _run(name, **kwargs):
    out = io.StringIO()
    call_command(name, stdout=out, **kwargs)
    return out.getvalue()


class NotifyStaffFormatTests(TestCase):
    def setUp(self):
        salon = Salon.objects.create(name="Ping Salon", timezone="UTC")
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

    def _expected_text(self, dry_run=False, note_pk=None):
        describe = (
            f"StaffNotification staff_member={self.member} "
            f"staff_member_id={self.member.pk} "
            f"appointment_id={self.appt.pk} kind=arrived")
        if dry_run:
            return (f"Dry run: would create {describe} "
                    f"-- no notification written.\n")
        return f"Created {describe} id={note_pk}.\n"

    def test_default_text_output_unchanged(self):
        out = _run("notify_staff", staff_member_id=self.member.pk,
                   appointment_id=self.appt.pk)
        note = StaffNotification.objects.get()
        self.assertEqual(out, self._expected_text(note_pk=note.pk))

    def test_explicit_text_matches_default(self):
        out = _run("notify_staff", staff_member_id=self.member.pk,
                   appointment_id=self.appt.pk, format="text")
        note = StaffNotification.objects.get()
        self.assertEqual(out, self._expected_text(note_pk=note.pk))

    def test_explicit_text_dry_run_matches_default(self):
        out = _run("notify_staff", staff_member_id=self.member.pk,
                   appointment_id=self.appt.pk, dry_run=True,
                   format="text")
        self.assertEqual(out, self._expected_text(dry_run=True))
        self.assertEqual(StaffNotification.objects.count(), 0)

    def test_json_parses_as_one_object_with_correct_values(self):
        out = _run("notify_staff", staff_member_id=self.member.pk,
                   appointment_id=self.appt.pk, format="json")
        note = StaffNotification.objects.get()
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertNotIn("Created", out)
        self.assertEqual(json.loads(out), {
            "notification_id": note.pk,
            "staff_member_id": self.member.pk,
            "appointment_id": self.appt.pk,
            "kind": "arrived",
            "dry_run": False,
        })

    def test_json_dry_run_never_calls_writer(self):
        with mock.patch(
                "team.management.commands.notify_staff"
                ".notify_staff") as writer:
            out = _run("notify_staff", staff_member_id=self.member.pk,
                       appointment_id=self.appt.pk, dry_run=True,
                       format="json")
        writer.assert_not_called()
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertEqual(json.loads(out), {
            "notification_id": None,
            "staff_member_id": self.member.pk,
            "appointment_id": self.appt.pk,
            "kind": "arrived",
            "dry_run": True,
        })
        self.assertEqual(StaffNotification.objects.count(), 0)

    def test_json_via_cli(self):
        out = io.StringIO()
        call_command(
            "notify_staff", "--staff-member-id", str(self.member.pk),
            "--appointment-id", str(self.appt.pk),
            "--format", "json", stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["staff_member_id"], self.member.pk)
        self.assertEqual(data["appointment_id"], self.appt.pk)
        self.assertEqual(data["kind"], "arrived")
        self.assertFalse(data["dry_run"])
        self.assertEqual(StaffNotification.objects.count(), 1)

    def test_invalid_format_rejected(self):
        with self.assertRaises(CommandError):
            _run("notify_staff", staff_member_id=self.member.pk,
                 appointment_id=self.appt.pk, format="bogus")
        self.assertEqual(StaffNotification.objects.count(), 0)
        with self.assertRaises(CommandError):
            _run("notify_staff", staff_member_id=999999,
                 appointment_id=self.appt.pk, format="json")
