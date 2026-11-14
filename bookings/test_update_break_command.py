"""Tests for the update_break management command.

Thin wrapper around ``bookings.breaks.update_break``: pins that
a real run updates only the given fields, ``--dry-run`` writes
nothing but prints the merged would-be break (validation still
applied, incl. the merged-pair rule), no-field / unknown break /
unknown salon / salon mismatch surface as ``CommandError`` with
nothing written. Fixtures are tiny synthetic records.
"""
import datetime
import io
import json

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


class UpdateBreakCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.brk = Break.objects.create(
            staff_member=self.staff, start=at(12), end=at(12, 30),
            paid=False)

    def fresh(self):
        return Break.objects.get(pk=self.brk.pk)

    def test_real_run_updates_given_fields_only(self):
        out = io.StringIO()
        call_command("update_break", break_id=self.brk.pk,
                     ends_at=at(13), paid=True, stdout=out)
        fresh = self.fresh()
        self.assertEqual((fresh.start, fresh.end, fresh.paid),
                         (at(12), at(13), True))
        self.assertIn("Updated break", out.getvalue())

    def test_real_run_string_args_and_unpaid_flag(self):
        Break.objects.filter(pk=self.brk.pk).update(paid=True)
        call_command(
            "update_break", "--break-id", str(self.brk.pk),
            "--salon-id", str(self.salon.pk),
            "--starts-at", "2026-11-02T13:00:00+00:00",
            "--ends-at", "2026-11-02T13:30:00Z", "--unpaid",
            stdout=io.StringIO())
        fresh = self.fresh()
        self.assertEqual((fresh.start, fresh.end, fresh.paid),
                         (at(13), at(13, 30), False))

    def test_dry_run_writes_nothing_but_prints_merged(self):
        out = io.StringIO()
        call_command("update_break", break_id=self.brk.pk,
                     salon_id=self.salon.pk, ends_at=at(13),
                     paid=True, dry_run=True, stdout=out)
        fresh = self.fresh()
        self.assertEqual((fresh.end, fresh.paid), (at(12, 30), False))
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn(at(12).isoformat(), text)
        self.assertIn(at(13).isoformat(), text)
        self.assertIn("paid=True", text)

    def test_dry_run_flag_form(self):
        out = io.StringIO()
        call_command(
            "update_break", "--break-id", str(self.brk.pk),
            "--paid", "--dry-run", stdout=out)
        self.assertIn("Dry run", out.getvalue())
        self.assertFalse(self.fresh().paid)

    def test_merged_pair_violation_is_command_error(self):
        for kwargs in ({"starts_at": at(13)}, {"ends_at": at(12)}):
            with self.assertRaises(CommandError, msg=repr(kwargs)):
                call_command("update_break", break_id=self.brk.pk,
                             dry_run=True, stdout=io.StringIO(), **kwargs)
            with self.assertRaises(CommandError, msg=repr(kwargs)):
                call_command("update_break", break_id=self.brk.pk,
                             stdout=io.StringIO(), **kwargs)
        self.assertEqual((self.fresh().start, self.fresh().end),
                         (at(12), at(12, 30)))

    def test_no_field_given_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command("update_break", break_id=self.brk.pk,
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("update_break", break_id=self.brk.pk,
                         dry_run=True, stdout=io.StringIO())

    def test_unknown_break_salon_and_mismatch_are_command_errors(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        for kwargs in ({"break_id": 999999},
                       {"break_id": self.brk.pk, "salon_id": 999999},
                       {"break_id": self.brk.pk, "salon_id": other.pk}):
            with self.assertRaises(CommandError, msg=repr(kwargs)):
                call_command("update_break", paid=True,
                             stdout=io.StringIO(), **kwargs)
        self.assertFalse(self.fresh().paid)


class UpdateBreakCommandFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.brk = Break.objects.create(
            staff_member=self.staff, start=at(12), end=at(12, 30),
            paid=False)

    def fresh(self):
        return Break.objects.get(pk=self.brk.pk)

    def test_default_text_output_unchanged(self):
        out = io.StringIO()
        call_command("update_break", break_id=self.brk.pk,
                     ends_at=at(13), paid=True, stdout=out)
        self.assertEqual(
            out.getvalue(),
            f"Updated break {self.brk.pk} for staff member "
            f"{self.staff.pk}: start={at(12).isoformat()} "
            f"end={at(13).isoformat()} paid=True\n")

    def test_default_text_dry_run_output_unchanged(self):
        out = io.StringIO()
        call_command("update_break", break_id=self.brk.pk,
                     ends_at=at(13), paid=True, dry_run=True, stdout=out)
        self.assertEqual((self.fresh().end, self.fresh().paid),
                         (at(12, 30), False))
        self.assertEqual(
            out.getvalue(),
            f"Dry run: would update break {self.brk.pk} for "
            f"staff member {self.staff.pk}: "
            f"start={at(12).isoformat()} end={at(13).isoformat()} "
            f"paid=True -- no break written.\n")

    def test_format_json_updates_and_reports_fields(self):
        out = io.StringIO()
        call_command(
            "update_break", "--break-id", str(self.brk.pk),
            "--ends-at", "2026-11-02T13:00:00+00:00",
            "--paid", "--format", "json", stdout=out)
        text = out.getvalue()
        fresh = self.fresh()
        self.assertEqual((fresh.end, fresh.paid), (at(13), True))
        self.assertNotIn("Updated break", text)
        self.assertEqual(json.loads(text), {
            "break_id": self.brk.pk,
            "staff_member_id": self.staff.pk,
            "salon_id": self.salon.pk,
            "start": at(12).isoformat(),
            "end": at(13).isoformat(),
            "paid": True,
            "dry_run": False})

    def test_format_json_via_call_command_kwargs(self):
        out = io.StringIO()
        call_command("update_break", break_id=self.brk.pk,
                     ends_at=at(13), format="json", stdout=out)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["break_id"], self.brk.pk)
        self.assertEqual(payload["end"], at(13).isoformat())
        self.assertEqual(payload["paid"], False)
        self.assertFalse(payload["dry_run"])

    def test_dry_run_format_json_reports_and_writes_nothing(self):
        out = io.StringIO()
        call_command(
            "update_break", "--break-id", str(self.brk.pk),
            "--ends-at", "2026-11-02T13:00:00+00:00",
            "--paid", "--dry-run", "--format", "json", stdout=out)
        self.assertEqual((self.fresh().end, self.fresh().paid),
                         (at(12, 30), False))
        self.assertEqual(json.loads(out.getvalue()), {
            "break_id": self.brk.pk,
            "staff_member_id": self.staff.pk,
            "salon_id": self.salon.pk,
            "start": at(12).isoformat(),
            "end": at(13).isoformat(),
            "paid": True,
            "dry_run": True})

    def test_format_json_errors_still_command_error(self):
        with self.assertRaises(CommandError):
            call_command("update_break", break_id=999999, paid=True,
                         format="json", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("update_break", break_id=self.brk.pk,
                         ends_at=at(12), format="json",
                         stdout=io.StringIO())
        self.assertEqual((self.fresh().end, self.fresh().paid),
                         (at(12, 30), False))

    def test_invalid_format_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command("update_break", break_id=self.brk.pk,
                         paid=True, format="xml", stdout=io.StringIO())
        self.assertFalse(self.fresh().paid)
