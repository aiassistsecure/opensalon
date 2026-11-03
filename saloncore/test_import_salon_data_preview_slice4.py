"""import_salon_data --dry-run slice-4 preview (cycle 144).

Slice-4 sections (roster_patterns, shift_overrides,
attendance_records, breaks) gain the same read-only
import_preview as slices 1-3: would-create / would-update /
would-unchanged / would-skip counts mirroring the writer's
identity rules. Breaks are get_or_create in the writer, so an
existing break never previews as would-update.
Writer never entered in dry-run.
"""
import io
import json
import tempfile
from datetime import date, datetime, time, timedelta, timezone as dt_timezone

from django.core.management import call_command
from django.test import TestCase

from bookings.models import Break
from saloncore.management.commands.import_salon_data import SECTIONS
from saloncore.models import Salon, StaffLevel
from saloncore.test_import_salon_data import _minimal_data
from team.models import (
    AttendanceRecord, RosterPattern, ShiftOverride, StaffMember)

SLICE4 = ("roster_patterns", "shift_overrides",
          "attendance_records", "breaks")
MODELS = (RosterPattern, ShiftOverride, AttendanceRecord, Break)
AT = datetime(2026, 11, 2, 13, 55, tzinfo=dt_timezone.utc)
BRK = datetime(2026, 11, 2, 17, 0, tzinfo=dt_timezone.utc)


def _data():
    data = _minimal_data()
    data["roster_patterns"] = [
        {"id": 100, "staff_member_id": 60,
         "staff_member_external_id": "staff-1", "weekday": 0,
         "start_time": "09:00:00", "end_time": "17:00:00",
         "active": True}]
    data["shift_overrides"] = [
        {"id": 101, "staff_member_id": 60,
         "staff_member_external_id": "staff-1",
         "date": "2026-11-03", "is_off": False,
         "start_time": "10:00:00", "end_time": "16:00:00"}]
    data["attendance_records"] = [
        {"id": 102, "staff_member_id": 60,
         "staff_member_external_id": "staff-1",
         "event_type": "check_in",
         "recorded_at": "2026-11-02T13:55:00+00:00", "note": ""}]
    data["breaks"] = [
        {"id": 103, "staff_member_id": 60,
         "staff_member_external_id": "staff-1",
         "start": "2026-11-02T17:00:00+00:00",
         "end": "2026-11-02T17:30:00+00:00", "paid": True}]
    return data


class ImportSalonDataPreviewSlice4Tests(TestCase):
    def write_data(self, data):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, fh)
        fh.close()
        return fh.name

    def run_dry(self, data):
        out = io.StringIO()
        call_command("import_salon_data", self.write_data(data),
                     dry_run=True, stdout=out)
        return json.loads(out.getvalue())

    def counts(self):
        return {m.__name__: m.objects.count() for m in MODELS}

    def store_matching(self):
        salon = Salon.objects.create(
            name="TF6 Salon", timezone="UTC", currency="USD")
        level = StaffLevel.objects.create(
            salon=salon, name="Level 6", sort_order=6, active=True)
        staff = StaffMember.objects.create(
            salon=salon, external_id="staff-1",
            display_name="Stylist One", staff_level=level,
            online_bookable=True, active=True, pin="", email="")
        RosterPattern.objects.create(
            staff_member=staff, weekday=0, start_time=time(9, 0),
            end_time=time(17, 0), active=True)
        ShiftOverride.objects.create(
            staff_member=staff, date=date(2026, 11, 3), is_off=False,
            start_time=time(10, 0), end_time=time(16, 0))
        AttendanceRecord.objects.create(
            staff_member=staff, event_type="check_in",
            recorded_at=AT, note="")
        Break.objects.create(
            staff_member=staff, start=BRK,
            end=BRK + timedelta(minutes=30), paid=True)
        return staff

    def test_preview_present_on_slice4_sections(self):
        reports = self.run_dry(_data())
        self.assertEqual(set(reports), set(SECTIONS))
        for section in SLICE4:
            self.assertIn("import_preview", reports[section], section)

    def test_would_create_all_slice4_on_empty_db(self):
        reports = self.run_dry(_data())
        for section in SLICE4:
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["total"], preview["would_create"],
                 preview["would_update"], preview["would_unchanged"],
                 preview["would_skip"]), (1, 1, 0, 0, 0), section)
            self.assertEqual(preview["skipped_rows"], [], section)

    def test_would_unchanged_against_matching_stored(self):
        self.store_matching()
        reports = self.run_dry(_data())
        for section in SLICE4:
            preview = reports[section]["import_preview"]
            self.assertEqual(preview["would_unchanged"], 1, section)
            self.assertEqual(preview["would_create"], 0, section)

    def test_would_update_when_stored_fields_differ(self):
        self.store_matching()
        data = _data()
        data["roster_patterns"][0]["active"] = False
        data["shift_overrides"][0]["start_time"] = "11:00:00"
        data["attendance_records"][0]["note"] = "Late bus."
        data["breaks"][0]["paid"] = False
        reports = self.run_dry(data)
        for section in SLICE4[:3]:
            self.assertEqual(
                reports[section]["import_preview"]["would_update"],
                1, section)
        # Breaks are get_or_create: paid is creation-only, an
        # existing break is returned untouched — never an update.
        self.assertEqual(
            reports["breaks"]["import_preview"]["would_update"], 0)
        self.assertEqual(
            reports["breaks"]["import_preview"]["would_unchanged"], 1)

    def test_repeat_row_in_file_judged_against_first_row(self):
        data = _data()
        data["roster_patterns"].append(
            dict(data["roster_patterns"][0], id=104, active=False))
        data["shift_overrides"].append(
            dict(data["shift_overrides"][0], id=105))
        data["breaks"].append(
            dict(data["breaks"][0], id=106, paid=False))
        reports = self.run_dry(data)
        roster = reports["roster_patterns"]["import_preview"]
        self.assertEqual(
            (roster["would_create"], roster["would_update"]), (1, 1))
        shift = reports["shift_overrides"]["import_preview"]
        self.assertEqual(
            (shift["would_create"], shift["would_unchanged"]), (1, 1))
        brk = reports["breaks"]["import_preview"]
        self.assertEqual(
            (brk["would_create"], brk["would_unchanged"]), (1, 1))

    def test_dry_run_writes_nothing_explicit(self):
        self.store_matching()
        before = self.counts()
        data = _data()
        data["roster_patterns"][0]["active"] = False  # would-update
        data["attendance_records"].append(
            {"id": 107, "staff_member_id": 60,
             "staff_member_external_id": "staff-1",
             "event_type": "check_out",
             "recorded_at": "2026-11-02T22:00:00+00:00",
             "note": ""})  # would-create
        self.run_dry(data)
        self.assertEqual(self.counts(), before)
        self.assertTrue(RosterPattern.objects.get().active)
