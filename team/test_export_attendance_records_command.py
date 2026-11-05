"""Tests for export_attendance_records: stdout/file == service."""
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.attendance_record_export import (
    export_attendance_records,
    export_attendance_records_csv,
)
from team.models import AttendanceRecord, StaffMember

UTC = datetime.timezone.utc


class ExportAttendanceRecordsCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Record Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana")
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_in",
            recorded_at=datetime.datetime(
                2026, 10, 31, 9, 0, tzinfo=UTC),
            note="front desk")

    def test_stdout_matches_service_output(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_attendance_records_csv(self.salon))
        self.assertIn("Dana", out.getvalue())
        self.assertIn("check_in", out.getvalue())
        self.assertIn("front desk", out.getvalue())

    def test_output_file_matches_service_output(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as fh:
            path = fh.name
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_attendance_records_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_header_only(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=empty.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_attendance_records_csv(empty))

    def test_staff_member_id_filters_to_one_member(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        AttendanceRecord.objects.create(
            staff_member=eve, event_type="check_in",
            recorded_at=datetime.datetime(
                2026, 10, 31, 10, 0, tzinfo=UTC), note="eve note")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id,
                     staff_member_id=self.staff.id, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attendance_records_csv(
                self.salon, staff_member=self.staff))
        self.assertIn("Dana", out.getvalue())
        self.assertNotIn("Eve", out.getvalue())
        self.assertNotIn("eve note", out.getvalue())

    def test_no_staff_member_id_is_salon_wide_default(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_attendance_records_csv(self.salon))
        self.assertEqual(
            out.getvalue(),
            export_attendance_records_csv(
                self.salon, staff_member=None))

    def test_unknown_staff_member_id_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         salon_id=self.salon.id,
                         staff_member_id=999999,
                         stdout=io.StringIO())

    def test_staff_member_from_other_salon_raises(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        theirs = StaffMember.objects.create(
            salon=other_salon, display_name="Other Dana")
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         salon_id=self.salon.id,
                         staff_member_id=theirs.id,
                         stdout=io.StringIO())

    def test_date_window_matches_service(self):
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_in",
            recorded_at=datetime.datetime(
                2026, 11, 5, 9, 0, tzinfo=UTC), note="later")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id,
                     start_date="2026-10-31", end_date="2026-10-31",
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attendance_records_csv(
                self.salon, start=datetime.date(2026, 10, 31),
                end=datetime.date(2026, 10, 31)))
        self.assertIn("front desk", out.getvalue())
        self.assertNotIn("later", out.getvalue())

    def test_date_window_cli_spelling(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     "--salon-id", str(self.salon.id),
                     "--start-date", "2026-11-01",
                     "--end-date", "2026-11-01", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attendance_records_csv(
                self.salon, start=datetime.date(2026, 11, 1),
                end=datetime.date(2026, 11, 1)))
        self.assertNotIn("front desk", out.getvalue())

    def test_date_window_composes_with_staff_member_id(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        AttendanceRecord.objects.create(
            staff_member=eve, event_type="check_in",
            recorded_at=datetime.datetime(
                2026, 10, 31, 10, 0, tzinfo=UTC), note="eve note")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id,
                     staff_member_id=self.staff.id,
                     start_date=datetime.date(2026, 10, 31),
                     end_date=datetime.date(2026, 10, 31), stdout=out)
        self.assertIn("Dana", out.getvalue())
        self.assertNotIn("Eve", out.getvalue())

    def test_start_date_only_is_unbounded_end(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id,
                     start_date=datetime.date(2026, 11, 1), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attendance_records_csv(
                self.salon, start=datetime.date(2026, 11, 1)))
        self.assertNotIn("front desk", out.getvalue())

    def test_invalid_date_and_reversed_range_raise(self):
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         salon_id=self.salon.id,
                         start_date="not-a-date", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         salon_id=self.salon.id,
                         start_date=datetime.date(2026, 11, 2),
                         end_date=datetime.date(2026, 11, 1),
                         stdout=io.StringIO())

    def test_event_type_filters(self):
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_out",
            recorded_at=datetime.datetime(
                2026, 10, 31, 17, 0, tzinfo=UTC), note="done")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, event_type="check_in",
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attendance_records_csv(
                self.salon, event_type="check_in"))
        self.assertIn("front desk", out.getvalue())
        self.assertNotIn("done", out.getvalue())

    def test_event_type_cli_spelling(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     "--salon-id", str(self.salon.id),
                     "--event-type", "check_out", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attendance_records_csv(
                self.salon, event_type="check_out"))
        self.assertNotIn("front desk", out.getvalue())

    def test_no_event_type_is_default(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_attendance_records_csv(self.salon, event_type=None))

    def test_event_type_composes_with_staff_and_window(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        AttendanceRecord.objects.create(
            staff_member=eve, event_type="check_in",
            recorded_at=datetime.datetime(
                2026, 10, 31, 10, 0, tzinfo=UTC), note="eve note")
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_out",
            recorded_at=datetime.datetime(
                2026, 10, 31, 17, 0, tzinfo=UTC), note="dana out")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id,
                     staff_member_id=self.staff.id,
                     start_date=datetime.date(2026, 10, 31),
                     end_date=datetime.date(2026, 10, 31),
                     event_type="check_in", stdout=out)
        self.assertIn("front desk", out.getvalue())
        self.assertNotIn("eve note", out.getvalue())
        self.assertNotIn("dana out", out.getvalue())

    def test_unknown_salon_required_id_and_unwritable(self):
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         salon_id=999999, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_attendance_records", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         salon_id=self.salon.id,
                         output="/nonexistent-dir/out.csv",
                         stdout=io.StringIO())

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_attendance_records_csv(self.salon))

    def test_explicit_csv_format_matches_service(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_attendance_records_csv(self.salon))

    def test_csv_flag_matches_service(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     "--salon-id", str(self.salon.id),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_attendance_records_csv(self.salon))

    def test_json_output_parses_and_equals_dict_service_rows(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_attendance_records(self.salon))
        self.assertIn("Dana", out.getvalue())
        self.assertIn("check_in", out.getvalue())
        self.assertIn("front desk", out.getvalue())

    def test_json_flag_matches_dict_service(self):
        out = io.StringIO()
        call_command("export_attendance_records",
                     "--salon-id", str(self.salon.id),
                     "--format", "json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()),
                         export_attendance_records(self.salon))

    def test_json_empty_salon_is_empty_list(self):
        empty = Salon.objects.create(name="Empty JSON", timezone="UTC")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=empty.id, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        self.assertEqual(json.loads(out.getvalue()),
                         export_attendance_records(empty))

    def test_json_composes_with_staff_member_id(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        AttendanceRecord.objects.create(
            staff_member=eve, event_type="check_in",
            recorded_at=datetime.datetime(
                2026, 10, 31, 10, 0, tzinfo=UTC), note="eve note")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id,
                     staff_member_id=self.staff.id, format="json",
                     stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_attendance_records(
                self.salon, staff_member=self.staff))
        self.assertNotIn("eve note", out.getvalue())

    def test_json_composes_with_event_type_and_window(self):
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_out",
            recorded_at=datetime.datetime(
                2026, 10, 31, 17, 0, tzinfo=UTC), note="done")
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_in",
            recorded_at=datetime.datetime(
                2026, 11, 5, 9, 0, tzinfo=UTC), note="later")
        out = io.StringIO()
        call_command("export_attendance_records",
                     salon_id=self.salon.id, format="json",
                     event_type="check_in",
                     start_date=datetime.date(2026, 10, 31),
                     end_date=datetime.date(2026, 10, 31), stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_attendance_records(
                self.salon, event_type="check_in",
                start=datetime.date(2026, 10, 31),
                end=datetime.date(2026, 10, 31)))
        self.assertIn("front desk", out.getvalue())
        self.assertNotIn("done", out.getvalue())
        self.assertNotIn("later", out.getvalue())

    def test_json_output_file_matches_dict_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "attendance.json")
            out = io.StringIO()
            call_command("export_attendance_records",
                         salon_id=self.salon.id, format="json",
                         output=path, stdout=out)
            self.assertEqual(out.getvalue(), "")
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(
                    json.loads(fh.read()),
                    export_attendance_records(self.salon))

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         salon_id=self.salon.id, format="xml",
                         stdout=io.StringIO())

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("export_attendance_records",
                         "--salon-id", str(self.salon.id),
                         "--format", "xml", stdout=io.StringIO())
