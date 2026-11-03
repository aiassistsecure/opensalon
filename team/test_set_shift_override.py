"""Tests for the shift-override service + set_shift_override command.

The service (team.shift_overrides) is the roster OFF-switch
write path: one member, one date, a placed shift or a full
day off; undo clears the override. The command is a thin
wrapper around it, with --dry-run previewing without writing.
Every write is verified through the one resolver,
team.availability.roster_availability (override-first).
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.availability import roster_availability
from team.models import RosterPattern, ShiftOverride, StaffMember
from team.shift_overrides import (
    clear_shift_override, set_shift_override,
)

SAT = datetime.date(2026, 10, 31)  # a Saturday
T9 = datetime.time(9, 0)
T17 = datetime.time(17, 0)


def _run(**kwargs):
    out = io.StringIO()
    call_command("set_shift_override", stdout=out, **kwargs)
    return out.getvalue()


class SetShiftOverrideServiceTests(TestCase):
    def setUp(self):
        salon = Salon.objects.create(
            name="Mint", timezone="America/New_York")
        self.member = StaffMember.objects.create(
            salon=salon, display_name="Dawn Davalos")
        RosterPattern.objects.create(
            staff_member=self.member, weekday=5,
            start_time=T9, end_time=T17)

    def hours(self, day=SAT):
        return [(i.start.strftime("%H:%M"), i.end.strftime("%H:%M"))
                for i in roster_availability(self.member, day).intervals]

    def test_placed_shift_writes_override_resolver_sees(self):
        ov = set_shift_override(
            self.member, SAT, start_time=datetime.time(10, 0),
            end_time=datetime.time(14, 0))
        self.assertFalse(ov.is_off)
        self.assertEqual((ov.start_time, ov.end_time),
                         (datetime.time(10, 0), datetime.time(14, 0)))
        self.assertEqual(self.hours(), [("10:00", "14:00")])

    def test_day_off_writes_override_resolver_sees_empty(self):
        ov = set_shift_override(self.member, SAT, is_off=True)
        self.assertTrue(ov.is_off)
        self.assertIsNone(ov.start_time)
        self.assertIsNone(ov.end_time)
        self.assertEqual(self.hours(), [])

    def test_set_replaces_existing_override_wholesale(self):
        set_shift_override(self.member, SAT, is_off=True)
        set_shift_override(
            self.member, SAT, start_time=datetime.time(11, 0),
            end_time=datetime.time(15, 0))
        self.assertEqual(ShiftOverride.objects.count(), 1)
        self.assertEqual(self.hours(), [("11:00", "15:00")])

    def test_clear_is_undo_and_pattern_speaks_again(self):
        set_shift_override(self.member, SAT, is_off=True)
        self.assertTrue(clear_shift_override(self.member, SAT))
        self.assertEqual(ShiftOverride.objects.count(), 0)
        self.assertEqual(self.hours(), [("09:00", "17:00")])
        self.assertFalse(clear_shift_override(self.member, SAT))

    def test_invalid_shapes_write_nothing(self):
        for kwargs in (
            {},  # neither shift nor off
            {"start_time": T9},  # missing end
            {"start_time": T17, "end_time": T9},  # backwards
            {"is_off": True, "start_time": T9, "end_time": T17},
        ):
            with self.assertRaises(ValidationError):
                set_shift_override(self.member, SAT, **kwargs)
        self.assertEqual(ShiftOverride.objects.count(), 0)


class SetShiftOverrideCommandTests(TestCase):
    def setUp(self):
        salon = Salon.objects.create(
            name="Mint", timezone="America/New_York")
        self.member = StaffMember.objects.create(
            salon=salon, display_name="Dawn Davalos")
        RosterPattern.objects.create(
            staff_member=self.member, weekday=5,
            start_time=T9, end_time=T17)

    def hours(self):
        return [(i.start.strftime("%H:%M"), i.end.strftime("%H:%M"))
                for i in roster_availability(self.member, SAT).intervals]

    def test_command_placed_shift(self):
        out = _run(staff_member_id=self.member.pk, date=SAT,
                   start="10:00", end="14:00")
        self.assertIn("10:00", out)
        self.assertEqual(self.hours(), [("10:00", "14:00")])

    def test_command_placed_shift_via_cli(self):
        out = io.StringIO()
        call_command(
            "set_shift_override", "--staff-member-id",
            str(self.member.pk), "--date", "2026-10-31",
            "--start", "11:00", "--end", "15:00", stdout=out)
        self.assertEqual(self.hours(), [("11:00", "15:00")])

    def test_command_day_off(self):
        out = _run(staff_member_id=self.member.pk, date=SAT,
                   is_off=True)
        self.assertIn("is_off=True", out)
        self.assertEqual(self.hours(), [])

    def test_command_clear_is_undo(self):
        _run(staff_member_id=self.member.pk, date=SAT, is_off=True)
        out = _run(staff_member_id=self.member.pk, date=SAT,
                   clear=True)
        self.assertIn("Cleared", out)
        self.assertEqual(ShiftOverride.objects.count(), 0)
        self.assertEqual(self.hours(), [("09:00", "17:00")])

    def test_dry_run_placed_shift_writes_nothing(self):
        out = _run(staff_member_id=self.member.pk, date=SAT,
                   start="10:00", end="14:00", dry_run=True)
        self.assertIn("Dry run: would set", out)
        self.assertIn("10:00", out)
        self.assertEqual(ShiftOverride.objects.count(), 0)
        self.assertEqual(self.hours(), [("09:00", "17:00")])

    def test_dry_run_off_and_clear_write_nothing(self):
        out = _run(staff_member_id=self.member.pk, date=SAT,
                   is_off=True, dry_run=True)
        self.assertIn("is_off=True", out)
        self.assertEqual(ShiftOverride.objects.count(), 0)
        set_shift_override(self.member, SAT, is_off=True)
        out = _run(staff_member_id=self.member.pk, date=SAT,
                   clear=True, dry_run=True)
        self.assertIn("Dry run: would clear", out)
        self.assertEqual(ShiftOverride.objects.count(), 1)
        self.assertEqual(self.hours(), [])

    def test_unknown_staff_and_bad_shape_are_errors(self):
        with self.assertRaises(CommandError):
            _run(staff_member_id=self.member.pk + 1000, date=SAT,
                 is_off=True)
        with self.assertRaises(CommandError):
            _run(staff_member_id=self.member.pk, date=SAT)
        with self.assertRaises(CommandError):
            _run(staff_member_id=self.member.pk, date=SAT,
                 clear=True, is_off=True)
        self.assertEqual(ShiftOverride.objects.count(), 0)
