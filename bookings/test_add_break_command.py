"""Tests for the add_break management command.

The command is a thin wrapper around ``bookings.breaks.add_break``:
these tests pin that a real run creates exactly one break for the
right staff member (paid with ``--paid``, unpaid by default), that
``--dry-run`` creates none but prints the would-be break (with the
service's validation still applied), and that unknown
salon/staff, salon mismatch, and invalid times surface as
``CommandError`` with nothing written. Fixtures are tiny
synthetic records -- unit logic only.
"""
import datetime
import io

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Break
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


def at(hour, minute=0):
    return datetime.datetime.combine(DAY, datetime.time(hour, minute),
                                     tzinfo=UTC)


class AddBreakCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")

    def test_real_run_creates_paid_break(self):
        out = io.StringIO()
        call_command(
            "add_break", staff_member_id=self.staff.pk,
            starts_at=at(12), ends_at=at(12, 30), paid=True, stdout=out)
        self.assertEqual(Break.objects.count(), 1)
        (created,) = Break.objects.all()
        self.assertEqual(created.staff_member, self.staff)
        self.assertEqual(created.start, at(12))
        self.assertEqual(created.end, at(12, 30))
        self.assertTrue(created.paid)
        self.assertIn("break", out.getvalue())

    def test_real_run_string_args_unpaid_by_default(self):
        out = io.StringIO()
        call_command(
            "add_break", "--staff-member-id", str(self.staff.pk),
            "--salon-id", str(self.salon.pk),
            "--starts-at", "2026-11-02T13:00:00+00:00",
            "--ends-at", "2026-11-02T14:00:00+00:00", stdout=out)
        self.assertEqual(Break.objects.count(), 1)
        (created,) = Break.objects.all()
        self.assertEqual(created.start, at(13))
        self.assertEqual(created.end, at(14))
        self.assertFalse(created.paid)

    def test_real_run_paid_flag_form(self):
        call_command(
            "add_break", "--staff-member-id", str(self.staff.pk),
            "--starts-at", "2026-11-02T12:00:00Z",
            "--ends-at", "2026-11-02T12:30:00Z",
            "--paid", stdout=io.StringIO())
        self.assertTrue(Break.objects.get().paid)

    def test_dry_run_creates_none_but_prints_would_be_break(self):
        out = io.StringIO()
        call_command(
            "add_break", staff_member_id=self.staff.pk,
            salon_id=self.salon.pk, starts_at=at(12), ends_at=at(12, 30),
            paid=True, dry_run=True, stdout=out)
        self.assertEqual(Break.objects.count(), 0)
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn(str(self.staff.pk), text)
        self.assertIn("paid=True", text)
        self.assertIn(at(12).isoformat(), text)

    def test_dry_run_flag_form(self):
        out = io.StringIO()
        call_command(
            "add_break", "--staff-member-id", str(self.staff.pk),
            "--starts-at", "2026-11-02T12:00:00+00:00",
            "--ends-at", "2026-11-02T12:30:00+00:00",
            "--dry-run", stdout=out)
        self.assertEqual(Break.objects.count(), 0)
        self.assertIn("Dry run", out.getvalue())

    def test_dry_run_invalid_span_is_command_error_and_writes_nothing(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_break", staff_member_id=self.staff.pk,
                starts_at=at(12), ends_at=at(12), dry_run=True,
                stdout=io.StringIO())
        self.assertEqual(Break.objects.count(), 0)

    def test_end_at_or_before_start_is_command_error(self):
        for ends_at in (at(12), at(11, 30)):
            with self.assertRaises(CommandError):
                call_command(
                    "add_break", staff_member_id=self.staff.pk,
                    starts_at=at(12), ends_at=ends_at,
                    stdout=io.StringIO())
        self.assertEqual(Break.objects.count(), 0)

    def test_unknown_staff_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_break", staff_member_id=999999,
                starts_at=at(12), ends_at=at(12, 30),
                stdout=io.StringIO())
        self.assertEqual(Break.objects.count(), 0)

    def test_unknown_salon_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_break", staff_member_id=self.staff.pk, salon_id=999999,
                starts_at=at(12), ends_at=at(12, 30),
                stdout=io.StringIO())
        self.assertEqual(Break.objects.count(), 0)

    def test_staff_outside_salon_is_command_error(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        with self.assertRaises(CommandError):
            call_command(
                "add_break", staff_member_id=self.staff.pk,
                salon_id=other.pk, starts_at=at(12), ends_at=at(12, 30),
                stdout=io.StringIO())
        self.assertEqual(Break.objects.count(), 0)

    def test_dry_run_unknown_staff_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "add_break", staff_member_id=999999,
                starts_at=at(12), ends_at=at(12, 30), dry_run=True,
                stdout=io.StringIO())
        self.assertEqual(Break.objects.count(), 0)
