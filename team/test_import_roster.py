"""Tests for the import_roster command + team.roster_import service.

Fixtures are tiny committed CSV documents under
``team/test_fixtures/`` -- unit logic only, no real salon data,
synthetic ids only. (Committed fixtures, not temp files: the
command takes a path, and a shipped fixture exercises exactly
that path argument.)
"""
import datetime
import io
import json
import os

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.models import RosterPattern, StaffMember

FIXTURES = os.path.join(os.path.dirname(__file__), "test_fixtures")


def _fixture(name):
    return os.path.join(FIXTURES, name)


class ImportRosterTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="My Salon")
        StaffMember.objects.create(
            salon=self.salon, external_id="stf-1", display_name="Test One")
        StaffMember.objects.create(
            salon=self.salon, external_id="stf-2", display_name="Test Two")

    def run_import(self, fixture="roster_valid.csv", **kwargs):
        out = io.StringIO()
        call_command("import_roster", _fixture(fixture), stdout=out, **kwargs)
        return out.getvalue()

    def test_creates_patterns_resolved_by_external_id(self):
        out = self.run_import()
        self.assertIn('"created": 3', out)
        self.assertIn('"skipped": 0', out)
        one = StaffMember.objects.get(external_id="stf-1")
        patterns = RosterPattern.objects.filter(staff_member=one)
        self.assertEqual(patterns.count(), 2)
        monday = patterns.get(weekday=0)
        self.assertEqual(monday.start_time, datetime.time(9, 0))
        self.assertEqual(monday.end_time, datetime.time(17, 0))
        friday = RosterPattern.objects.get(staff_member__external_id="stf-2")
        self.assertEqual(friday.weekday, 4)
        self.assertEqual(friday.end_time, datetime.time(13, 0))

    def test_name_spelling_columns_also_resolve(self):
        out = self.run_import("roster_by_name.csv")
        self.assertIn('"created": 1', out)
        pattern = RosterPattern.objects.get()
        self.assertEqual(pattern.staff_member.display_name, "Test One")
        self.assertEqual(pattern.weekday, 1)
        self.assertEqual(pattern.start_time, datetime.time(8, 0))

    def test_rerun_is_idempotent(self):
        self.run_import()
        out = self.run_import()
        self.assertIn('"created": 0', out)
        self.assertIn('"existing": 3', out)
        self.assertEqual(RosterPattern.objects.count(), 3)

    def test_unknown_member_skipped_and_counted(self):
        out = self.run_import("roster_unknown.csv")
        self.assertIn('"skipped_unknown_member": 1', out)
        self.assertIn('"skipped": 1', out)
        self.assertEqual(RosterPattern.objects.count(), 3)

    def test_bad_rows_skipped_and_counted(self):
        out = self.run_import("roster_bad.csv")
        self.assertIn('"skipped_bad_row": 4', out)
        self.assertIn('"created": 0', out)
        self.assertEqual(RosterPattern.objects.count(), 0)

    def test_existing_pattern_never_overwritten(self):
        member = StaffMember.objects.get(external_id="stf-1")
        corrected = RosterPattern.objects.create(
            staff_member=member, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0),
            active=False)
        self.run_import()
        corrected.refresh_from_db()
        self.assertFalse(corrected.active)  # human correction preserved
        self.assertEqual(
            RosterPattern.objects.filter(
                staff_member=member, weekday=0).count(), 1)

    def test_missing_file_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("import_roster", "/nonexistent/roster.csv")


class ImportRosterDryRunTests(TestCase):
    def test_dry_run_writes_nothing(self):
        Salon.objects.create(name="My Salon")
        out = io.StringIO()
        call_command(
            "import_roster", _fixture("roster_valid.csv"),
            dry_run=True, stdout=out)
        report = json.loads(out.getvalue())
        self.assertEqual(report["record_count"], 3)
        self.assertIn("staff_member_external_id", report["mapped_keys"])
        self.assertEqual(RosterPattern.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 1)  # only the salon above
        self.assertNotIn("IMPORT_SUMMARY", out.getvalue())

    def test_dry_run_creates_no_salon(self):
        out = io.StringIO()
        call_command(
            "import_roster", _fixture("roster_valid.csv"),
            dry_run=True, stdout=out)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(StaffMember.objects.count(), 0)
