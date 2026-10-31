"""Tests for the export_roster_availability management command.

The command is a thin wrapper around
``team.availability_export.export_roster_availability_csv``:
these tests pin that its stdout and file output match that
service verbatim, that it exports ONE staff member (not the
whole salon roster served by ``export_availability_csv`` /
``export_salon_roster_csv``), and that invalid input raises
CommandError. Fixtures are tiny synthetic records -- unit
logic only.

The command class is loaded explicitly via
``load_command_class("team", "export_roster_availability")``
and passed to ``call_command`` so these tests pin this app's
command by name.
"""
import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command, load_command_class
from django.test import TestCase

from saloncore.models import Salon
from team.availability_export import (
    export_availability_csv,
    export_roster_availability_csv,
    export_salon_roster_csv,
)
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)
TUESDAY = datetime.date(2026, 11, 3)


def _cmd():
    return load_command_class("team", "export_roster_availability")


class ExportRosterAvailabilityCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other_staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        for member in (self.staff, self.other_staff):
            RosterPattern.objects.create(
                staff_member=member, weekday=0,
                start_time=datetime.time(9, 0),
                end_time=datetime.time(17, 0))

    def run_export(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("staff_member_id", self.staff.pk)
        kwargs.setdefault("date", MONDAY)
        call_command(_cmd(), stdout=out, **kwargs)
        return out.getvalue()

    def test_command_class_is_team_export_roster_availability(self):
        self.assertIsNotNone(_cmd())

    def test_stdout_matches_service(self):
        out = self.run_export()
        self.assertEqual(
            out, export_roster_availability_csv(self.staff, MONDAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            _cmd(), "--salon-id", str(self.salon.pk),
            "--staff-member-id", str(self.staff.pk),
            "--date", MONDAY.isoformat(), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_roster_availability_csv(self.staff, MONDAY))

    def test_stdout_matches_service_via_global_name(self):
        out = io.StringIO()
        call_command(
            "export_roster_availability",
            salon_id=self.salon.pk, staff_member_id=self.staff.pk,
            date=MONDAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_roster_availability_csv(self.staff, MONDAY))

    def test_single_member_shape_differs_from_salon_roster(self):
        # The roster-availability service exports only the one
        # member; the salon-roster alias exports every member.
        out = self.run_export()
        self.assertEqual(
            out, export_roster_availability_csv(self.staff, MONDAY))
        self.assertNotEqual(out, export_salon_roster_csv(self.salon, MONDAY))
        self.assertNotEqual(out, export_availability_csv(self.salon, MONDAY))
        self.assertIn("Stylist One", out)
        self.assertNotIn("Stylist Two", out)
        # Header + exactly one data row for the one member.
        self.assertEqual(len(out.strip().splitlines()), 2)
        salon_out = export_salon_roster_csv(self.salon, MONDAY)
        self.assertIn("Stylist Two", salon_out)
        self.assertEqual(len(salon_out.strip().splitlines()), 3)

    def test_other_member_exports_only_that_member(self):
        out = self.run_export(staff_member_id=self.other_staff.pk)
        self.assertEqual(
            out,
            export_roster_availability_csv(self.other_staff, MONDAY))
        self.assertIn("Stylist Two", out)
        self.assertNotIn("Stylist One", out)

    def test_off_day_matches_service(self):
        out = self.run_export(date=TUESDAY)
        self.assertEqual(
            out, export_roster_availability_csv(self.staff, TUESDAY))
        self.assertEqual(len(out.strip().splitlines()), 2)

    def test_output_file_matches_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "roster_availability.csv")
            out = self.run_export(output=path)
            self.assertEqual(out, "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    fh.read(),
                    export_roster_availability_csv(self.staff, MONDAY))

    def test_unknown_salon_id_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(salon_id=self.salon.pk + 1000)

    def test_unknown_staff_member_id_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(staff_member_id=self.staff.pk + 1000)

    def test_staff_from_other_salon_is_command_error(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        outsider = StaffMember.objects.create(
            salon=other_salon, display_name="Outsider")
        with self.assertRaises(CommandError):
            self.run_export(staff_member_id=outsider.pk)
        # The same member exports fine under its own salon.
        out = io.StringIO()
        call_command(
            _cmd(), salon_id=other_salon.pk,
            staff_member_id=outsider.pk, date=MONDAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_roster_availability_csv(outsider, MONDAY))

    def test_invalid_date_is_command_error(self):
        with self.assertRaises(CommandError):
            self.run_export(date="not-a-date")
        with self.assertRaises(CommandError):
            self.run_export(date="2026-13-40")

    def test_unwritable_output_is_command_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing", "roster_availability.csv")
            with self.assertRaises(CommandError):
                self.run_export(output=path)
