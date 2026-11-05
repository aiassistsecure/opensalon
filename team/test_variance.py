"""Tests for rostered-vs-actual variance service, export, command."""
import csv
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from saloncore.models import Salon
from team.models import AttendanceRecord, RosterPattern, ShiftOverride, StaffMember
from team.variance import roster_variance
from team.variance_export import (
    VARIANCE_EXPORT_FIELDNAMES, export_roster_variance,
    export_roster_variance_csv)

MON = datetime.date(2026, 11, 2)  # Monday
TUE = datetime.date(2026, 11, 3)
WED = datetime.date(2026, 11, 4)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class RosterVarianceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        # Both rostered Mon-Wed 09:00-17:00 (480 min/day).
        for member in (self.staff, self.other):
            for weekday in (0, 1, 2):
                RosterPattern.objects.create(
                    staff_member=member, weekday=weekday,
                    start_time=datetime.time(9, 0),
                    end_time=datetime.time(17, 0))

    def _session(self, staff, day, start=(9, 0), end=(17, 0)):
        AttendanceRecord.objects.create(
            staff_member=staff, event_type="check_in",
            recorded_at=at(day, *start))
        if end is not None:
            AttendanceRecord.objects.create(
                staff_member=staff, event_type="check_out",
                recorded_at=at(day, *end))

    def test_full_attendance_zero_variance(self):
        for day in (MON, TUE, WED):
            self._session(self.staff, day)
        result = roster_variance(self.salon, MON, WED)
        entry = result.for_staff(self.staff)
        self.assertEqual(entry.rostered_minutes, 1440)
        self.assertEqual(entry.actual_minutes, 1440)
        self.assertEqual(entry.variance_minutes, 0)
        self.assertEqual((entry.days_rostered, entry.days_attended,
                          entry.absence_days), (3, 3, 0))
        self.assertEqual(result.start_date, MON)
        self.assertEqual(result.end_date, WED)

    def test_absence_and_short_day(self):
        self._session(self.staff, MON, end=(13, 0))  # 240 actual
        # Tue/Wed: no attendance at all.
        entry = roster_variance(self.salon, MON, WED).for_staff(self.staff)
        self.assertEqual(entry.actual_minutes, 240)
        self.assertEqual(entry.variance_minutes, 240 - 1440)
        self.assertEqual((entry.days_rostered, entry.days_attended, entry.absence_days), (3, 1, 2))

    def test_overtime_positive_variance_and_zero_fill(self):
        self._session(self.other, MON, start=(8, 0), end=(18, 0))
        result = roster_variance(self.salon, MON, MON)
        self.assertEqual(result.for_staff(self.other).variance_minutes, 120)
        # Stylist One rostered but absent that day.
        one = result.for_staff(self.staff)
        self.assertEqual((one.actual_minutes, one.absence_days), (0, 1))
        self.assertEqual(result.rostered_minutes, 960)
        self.assertEqual(result.variance_minutes, 600 - 960)

    def test_override_off_day_not_rostered_or_absent(self):
        ShiftOverride.objects.create(
            staff_member=self.staff, date=TUE, is_off=True)
        self._session(self.staff, MON)
        self._session(self.staff, WED)
        entry = roster_variance(self.salon, MON, WED).for_staff(self.staff)
        self.assertEqual(entry.rostered_minutes, 960)
        self.assertEqual((entry.days_rostered, entry.absence_days), (2, 0))

    def test_open_session_counts_attended_no_minutes(self):
        self._session(self.staff, MON, end=None)
        entry = roster_variance(self.salon, MON, MON).for_staff(self.staff)
        self.assertEqual((entry.actual_minutes, entry.days_attended,
                          entry.absence_days), (0, 1, 0))

    def test_reversed_and_missing_raise(self):
        with self.assertRaises(ValueError):
            roster_variance(self.salon, WED, MON)
        with self.assertRaises(ValueError):
            roster_variance(self.salon, None, MON)
        with self.assertRaises(ValueError):
            roster_variance(None, MON, WED)

    def test_salon_timezone_attribution(self):
        salon = Salon.objects.create(name="NY", timezone="America/New_York")
        member = StaffMember.objects.create(salon=salon, display_name="NY")
        RosterPattern.objects.create(
            staff_member=member, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        # 14:00-22:00 UTC Mon = 09:00-17:00 EST Mon.
        self._session(member, MON, start=(14, 0), end=(22, 0))
        entry = roster_variance(salon, MON, MON).for_staff(member)
        self.assertEqual((entry.rostered_minutes, entry.actual_minutes,
                          entry.variance_minutes), (480, 480, 0))

    def test_export_dict_and_csv_match_service(self):
        self._session(self.staff, MON)
        rows = export_roster_variance(self.salon, MON, WED)
        self.assertEqual(list(rows[0].keys()), VARIANCE_EXPORT_FIELDNAMES)
        row = [r for r in rows if r["staff_name"] == "Stylist One"][0]
        self.assertEqual((row["rostered_minutes"], row["actual_minutes"],
                          row["variance_minutes"], row["absence_days"]),
                         (1440, 480, -960, 2))
        parsed = list(csv.DictReader(io.StringIO(
            export_roster_variance_csv(self.salon, MON, WED))))
        self.assertEqual(parsed[0]["staff_name"], "Stylist One")
        self.assertEqual(parsed[0]["variance_minutes"], "-960")

    def test_command_stdout_and_errors(self):
        self._session(self.staff, MON)
        out = io.StringIO()
        call_command("export_roster_variance", salon_id=self.salon.pk,
                     start_date=MON, end_date=WED, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_roster_variance_csv(self.salon, MON, WED))
        with self.assertRaises(CommandError):
            call_command("export_roster_variance",
                         salon_id=self.salon.pk + 1000,
                         start_date=MON, end_date=WED, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_roster_variance", salon_id=self.salon.pk,
                         start_date=WED, end_date=MON, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_roster_variance", salon_id=self.salon.pk,
                         start_date="bad", end_date=WED, stdout=io.StringIO())

    def test_command_default_and_explicit_csv_match_service(self):
        self._session(self.staff, MON)
        want = export_roster_variance_csv(self.salon, MON, WED)
        out = io.StringIO()
        call_command("export_roster_variance", salon_id=self.salon.pk,
                     start_date=MON, end_date=WED, stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_roster_variance", salon_id=self.salon.pk,
                     start_date=MON, end_date=WED, format="csv", stdout=out)
        self.assertEqual(out.getvalue(), want)
        out = io.StringIO()
        call_command("export_roster_variance",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", str(MON), "--end-date", str(WED),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), want)

    def test_command_json_parses_and_equals_dict_service_rows(self):
        self._session(self.staff, MON)
        rows = export_roster_variance(self.salon, MON, WED)
        out = io.StringIO()
        call_command("export_roster_variance", salon_id=self.salon.pk,
                     start_date=MON, end_date=WED, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        self.assertEqual(
            out.getvalue(),
            json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")
        parsed = json.loads(out.getvalue())
        row = [r for r in parsed if r["staff_name"] == "Stylist One"][0]
        self.assertEqual((row["rostered_minutes"], row["variance_minutes"]),
                         (1440, -960))
        self.assertEqual(row["start_date"], MON.isoformat())

    def test_command_json_flag_matches_dict_service(self):
        out = io.StringIO()
        call_command("export_roster_variance",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", str(MON), "--end-date", str(WED),
                     "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_roster_variance(self.salon, MON, WED))

    def test_command_json_empty_salon_is_empty_list(self):
        empty = Salon.objects.create(name="Empty JSON", timezone="UTC")
        out = io.StringIO()
        call_command("export_roster_variance", salon_id=empty.pk,
                     start_date=MON, end_date=WED, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(out.getvalue(), "[]\n")

    def test_command_json_output_file_matches_dict_service(self):
        self._session(self.staff, MON)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "variance.json")
            out = io.StringIO()
            call_command("export_roster_variance", salon_id=self.salon.pk,
                         start_date=MON, end_date=WED, format="json",
                         output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(json.loads(written),
                         export_roster_variance(self.salon, MON, WED))
        self.assertEqual(out.getvalue(), "")

    def test_command_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_roster_variance", salon_id=self.salon.pk,
                         start_date=MON, end_date=WED, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_roster_variance",
                         "--salon-id", str(self.salon.pk),
                         "--start-date", str(MON), "--end-date", str(WED),
                         "--format", "xml", stdout=io.StringIO())
