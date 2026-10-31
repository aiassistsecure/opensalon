"""Tests for the export_roster management command.

The command is a thin wrapper around
``team.roster_export.export_roster_patterns_csv``: these tests
pin that its stdout and file output match that service verbatim
and that the export is scoped to the requested salon only.
Fixtures are tiny synthetic records -- unit logic only.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.models import RosterPattern, StaffMember
from team.roster_export import export_roster_patterns_csv


class ExportRosterCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0))

    def run_export(self, **kwargs):
        out = io.StringIO()
        call_command("export_roster", stdout=out, **kwargs)
        return out.getvalue()

    def test_stdout_matches_service(self):
        out = self.run_export(salon_id=self.salon.pk)
        self.assertEqual(out, export_roster_patterns_csv(self.salon))

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "roster.csv")
            out = self.run_export(salon_id=self.salon.pk, output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(), export_roster_patterns_csv(self.salon))

    def test_salon_scoping(self):
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Stylist")
        RosterPattern.objects.create(
            staff_member=other_staff, weekday=1,
            start_time=datetime.time(10, 0),
            end_time=datetime.time(18, 0))
        out = self.run_export(salon_id=self.salon.pk)
        self.assertEqual(out, export_roster_patterns_csv(self.salon))
        self.assertIn("Stylist One", out)
        self.assertNotIn("Other Stylist", out)
        other_out = self.run_export(salon_id=self.other_salon.pk)
        self.assertIn("Other Stylist", other_out)
        self.assertNotIn("Stylist One", other_out)

    def test_unknown_salon_id_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(salon_id=self.other_salon.pk + 1000)

    def test_salon_id_is_required(self):
        with self.assertRaises(CommandError):
            call_command("export_roster", stdout=io.StringIO())
