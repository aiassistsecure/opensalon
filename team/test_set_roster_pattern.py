"""Tests for the roster-pattern service + set_roster_pattern command.

The service (team.roster_patterns) is the roster ON-switch
write path: one member, one weekday, one perpetual block
that replaces that weekday's pattern wholesale. The command
is a thin wrapper around it, with a reads-only --dry-run
preview (no write-then-rollback). Every write is verified
through the one resolver, team.availability.roster_availability.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.availability import roster_availability
from team.models import RosterPattern, StaffMember
from team.roster_patterns import (
    preview_roster_pattern, set_roster_pattern,
)

MON = datetime.date(2026, 11, 2)  # a Monday
TUE = datetime.date(2026, 11, 3)  # a Tuesday
T9 = datetime.time(9, 0)
T17 = datetime.time(17, 0)


def _run(**kwargs):
    out = io.StringIO()
    call_command("set_roster_pattern", stdout=out, **kwargs)
    return out.getvalue()


class SetRosterPatternServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Mint", timezone="America/New_York")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dawn Davalos")

    def hours(self, day=MON):
        return [(i.start.strftime("%H:%M"), i.end.strftime("%H:%M"))
                for i in roster_availability(self.member, day).intervals]

    def test_set_writes_pattern_resolver_sees(self):
        pat = set_roster_pattern(
            self.member, 0, start_time=T9, end_time=T17)
        self.assertTrue(pat.active)
        self.assertEqual(self.hours(), [("09:00", "17:00")])
        self.assertEqual(self.hours(TUE), [])

    def test_set_replaces_weekday_wholesale_other_days_untouched(self):
        RosterPattern.objects.create(
            staff_member=self.member, weekday=0,
            start_time=T9, end_time=datetime.time(12, 0))
        RosterPattern.objects.create(
            staff_member=self.member, weekday=0,
            start_time=datetime.time(13, 0), end_time=T17)
        RosterPattern.objects.create(
            staff_member=self.member, weekday=1,
            start_time=T9, end_time=T17)
        set_roster_pattern(
            self.member, "monday",
            start_time=datetime.time(10, 0),
            end_time=datetime.time(14, 0))
        self.assertEqual(
            RosterPattern.objects.filter(
                staff_member=self.member, weekday=0).count(), 1)
        self.assertEqual(self.hours(), [("10:00", "14:00")])
        self.assertEqual(self.hours(TUE), [("09:00", "17:00")])

    def test_set_twice_same_window_is_one_pattern(self):
        set_roster_pattern(self.member, 0, start_time="09:00",
                           end_time="17:00")
        set_roster_pattern(self.member, 0, start_time=T9,
                           end_time=T17)
        self.assertEqual(RosterPattern.objects.count(), 1)

    def test_inactive_pattern_is_written_but_not_offered(self):
        pat = set_roster_pattern(
            self.member, 0, start_time=T9, end_time=T17,
            active=False)
        self.assertFalse(pat.active)
        self.assertEqual(self.hours(), [])

    def test_invalid_weekday_and_times_write_nothing(self):
        for kwargs in (
            {"weekday": 7, "start_time": T9, "end_time": T17},
            {"weekday": "funday", "start_time": T9, "end_time": T17},
            {"weekday": None, "start_time": T9, "end_time": T17},
            {"weekday": 0},
            {"weekday": 0, "start_time": T9},
            {"weekday": 0, "start_time": T17, "end_time": T9},
            {"weekday": 0, "start_time": T9, "end_time": T9},
            {"weekday": 0, "start_time": "25:00", "end_time": T17},
        ):
            with self.assertRaises(ValidationError):
                set_roster_pattern(self.member, **kwargs)
        self.assertEqual(RosterPattern.objects.count(), 0)

    def test_unknown_inactive_or_salonless_member_rejected(self):
        ghost = StaffMember(salon=self.salon, display_name="Ghost")
        with self.assertRaises(ValidationError):
            set_roster_pattern(ghost, 0, start_time=T9, end_time=T17)
        stale = StaffMember.objects.create(
            salon=self.salon, display_name="Stale")
        stale_pk, stale_salon = stale.pk, stale.salon
        stale.delete()
        stale.pk = stale_pk
        stale.salon = stale_salon
        with self.assertRaises(ValidationError):
            set_roster_pattern(stale, 0, start_time=T9, end_time=T17)
        self.member.active = False
        self.member.save()
        with self.assertRaises(ValidationError):
            set_roster_pattern(self.member, 0, start_time=T9,
                               end_time=T17)
        self.assertEqual(RosterPattern.objects.count(), 0)

    def test_preview_reads_only_and_reports_existing(self):
        RosterPattern.objects.create(
            staff_member=self.member, weekday=0,
            start_time=T9, end_time=T17)
        preview = preview_roster_pattern(
            self.member, 0, start_time=datetime.time(10, 0),
            end_time=datetime.time(14, 0))
        self.assertEqual(len(preview["existing"]), 1)
        self.assertEqual(preview["start_time"], datetime.time(10, 0))
        self.assertEqual(RosterPattern.objects.count(), 1)
        self.assertEqual(self.hours(), [("09:00", "17:00")])


class SetRosterPatternCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Mint", timezone="America/New_York")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dawn Davalos")

    def hours(self, day=MON):
        return [(i.start.strftime("%H:%M"), i.end.strftime("%H:%M"))
                for i in roster_availability(self.member, day).intervals]

    def test_command_sets_pattern(self):
        out = _run(staff_member_id=self.member.pk, weekday=0,
                   start="10:00", end="14:00")
        self.assertIn("10:00", out)
        self.assertEqual(self.hours(), [("10:00", "14:00")])

    def test_command_via_cli_weekday_name(self):
        out = io.StringIO()
        call_command(
            "set_roster_pattern", "--staff-member-id",
            str(self.member.pk), "--weekday", "Tuesday",
            "--start", "11:00", "--end", "15:00", stdout=out)
        self.assertEqual(self.hours(TUE), [("11:00", "15:00")])
        self.assertEqual(self.hours(), [])

    def test_dry_run_writes_nothing_and_keeps_existing(self):
        RosterPattern.objects.create(
            staff_member=self.member, weekday=0,
            start_time=T9, end_time=T17)
        out = _run(staff_member_id=self.member.pk, weekday=0,
                   start="10:00", end="14:00", dry_run=True)
        self.assertIn("Dry run: would set", out)
        self.assertIn("replacing 1 existing", out)
        self.assertEqual(RosterPattern.objects.count(), 1)
        self.assertEqual(self.hours(), [("09:00", "17:00")])

    def test_dry_run_on_empty_weekday_writes_nothing(self):
        out = _run(staff_member_id=self.member.pk, weekday=0,
                   start="10:00", end="14:00", dry_run=True)
        self.assertIn("replacing 0 existing", out)
        self.assertEqual(RosterPattern.objects.count(), 0)

    def test_unknown_member_and_bad_inputs_are_errors(self):
        with self.assertRaises(CommandError):
            _run(staff_member_id=self.member.pk + 1000, weekday=0,
                 start="10:00", end="14:00")
        with self.assertRaises(CommandError):
            _run(staff_member_id=self.member.pk, weekday=9,
                 start="10:00", end="14:00")
        with self.assertRaises(CommandError):
            _run(staff_member_id=self.member.pk, weekday=0,
                 start="14:00", end="10:00")
        with self.assertRaises(CommandError):
            _run(staff_member_id=self.member.pk, weekday=0,
                 start="not-a-time", end="14:00")
        with self.assertRaises(CommandError):
            _run(staff_member_id=self.member.pk,
                 start="10:00", end="14:00")
        self.assertEqual(RosterPattern.objects.count(), 0)
