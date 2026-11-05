"""Tests for export_shift_overrides: stdout/file == service."""
import datetime
import io
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import Salon
from team.models import ShiftOverride, StaffMember
from team.shift_override_export import export_shift_overrides_csv


class ExportShiftOverridesCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Override Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana")
        ShiftOverride.objects.create(
            staff_member=self.staff, date=datetime.date(2026, 10, 31),
            start_time=datetime.time(10, 0),
            end_time=datetime.time(14, 0))

    def test_stdout_matches_service_output(self):
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_shift_overrides_csv(self.salon))
        self.assertIn("Dana", out.getvalue())
        self.assertIn("2026-10-31", out.getvalue())

    def test_output_file_matches_service_output(self):
        with tempfile.NamedTemporaryFile(
                mode="w", suffix=".csv", delete=False,
                encoding="utf-8") as fh:
            path = fh.name
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id, output=path, stdout=out)
        with open(path, encoding="utf-8", newline="") as exported:
            data = exported.read()
        self.assertEqual(data, export_shift_overrides_csv(self.salon))
        self.assertEqual(out.getvalue(), "")

    def test_empty_salon_header_only(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=empty.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_shift_overrides_csv(empty))

    def test_staff_member_id_filters_to_one_member(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        ShiftOverride.objects.create(
            staff_member=eve, date=datetime.date(2026, 11, 7),
            is_off=True)
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id,
                     staff_member_id=self.staff.id, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(
                self.salon, staff_member=self.staff))
        self.assertIn("Dana", out.getvalue())
        self.assertNotIn("Eve", out.getvalue())

    def test_no_staff_member_id_is_salon_wide_default(self):
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_shift_overrides_csv(self.salon))
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(
                self.salon, staff_member=None))

    def test_unknown_staff_member_id_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides",
                         salon_id=self.salon.id,
                         staff_member_id=999999,
                         stdout=io.StringIO())

    def test_staff_member_from_other_salon_raises(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        theirs = StaffMember.objects.create(
            salon=other_salon, display_name="Other Dana")
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides",
                         salon_id=self.salon.id,
                         staff_member_id=theirs.id,
                         stdout=io.StringIO())

    def test_date_window_matches_service(self):
        ShiftOverride.objects.create(
            staff_member=self.staff,
            date=datetime.date(2026, 11, 7), is_off=True)
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id,
                     start_date="2026-10-31", end_date="2026-10-31",
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(
                self.salon, start_date=datetime.date(2026, 10, 31),
                end_date=datetime.date(2026, 10, 31)))
        self.assertIn("2026-10-31", out.getvalue())
        self.assertNotIn("2026-11-07", out.getvalue())

    def test_date_window_cli_spelling(self):
        out = io.StringIO()
        call_command("export_shift_overrides",
                     "--salon-id", str(self.salon.id),
                     "--start-date", "2026-11-01",
                     "--end-date", "2026-11-01", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(
                self.salon, start_date=datetime.date(2026, 11, 1),
                end_date=datetime.date(2026, 11, 1)))
        self.assertNotIn("2026-10-31", out.getvalue())

    def test_date_window_alias_flags(self):
        out = io.StringIO()
        call_command("export_shift_overrides",
                     "--salon-id", str(self.salon.id),
                     "--date-from", "2026-10-31",
                     "--date-to", "2026-10-31", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(
                self.salon, start_date=datetime.date(2026, 10, 31),
                end_date=datetime.date(2026, 10, 31)))
        self.assertIn("2026-10-31", out.getvalue())

    def test_date_window_composes_with_staff_member_id(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        ShiftOverride.objects.create(
            staff_member=eve, date=datetime.date(2026, 10, 31),
            is_off=True)
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id,
                     staff_member_id=self.staff.id,
                     start_date=datetime.date(2026, 10, 31),
                     end_date=datetime.date(2026, 10, 31), stdout=out)
        self.assertIn("Dana", out.getvalue())
        self.assertNotIn("Eve", out.getvalue())

    def test_start_date_only_is_unbounded_end(self):
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id,
                     start_date=datetime.date(2026, 11, 1), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(
                self.salon, start_date=datetime.date(2026, 11, 1)))
        self.assertNotIn("2026-10-31", out.getvalue())

    def test_reversed_window_exports_header_only(self):
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id,
                     start_date=datetime.date(2026, 11, 2),
                     end_date=datetime.date(2026, 11, 1), stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(
                self.salon, start_date=datetime.date(2026, 11, 2),
                end_date=datetime.date(2026, 11, 1)))
        self.assertNotIn("Dana", out.getvalue())

    def test_bad_start_date_raises(self):
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_shift_overrides",
                         "--salon-id", str(self.salon.id),
                         "--start-date", "not-a-date",
                         stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides",
                         salon_id=self.salon.id,
                         start_date="not-a-date", stdout=io.StringIO())

    def _off(self):
        return ShiftOverride.objects.create(
            staff_member=self.staff,
            date=datetime.date(2026, 11, 7), is_off=True)

    def test_is_off_only_flag(self):
        self._off()
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id, is_off_only=True,
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(self.salon, is_off=True))
        self.assertIn("2026-11-07", out.getvalue())
        self.assertNotIn("2026-10-31", out.getvalue())

    def test_is_on_only_flag(self):
        self._off()
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id, is_on_only=True,
                     stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(self.salon, is_off=False))
        self.assertIn("2026-10-31", out.getvalue())
        self.assertNotIn("2026-11-07", out.getvalue())

    def test_is_off_only_cli_spelling(self):
        self._off()
        out = io.StringIO()
        call_command("export_shift_overrides",
                     "--salon-id", str(self.salon.id),
                     "--is-off-only", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(self.salon, is_off=True))

    def test_is_on_only_cli_spelling(self):
        self._off()
        out = io.StringIO()
        call_command("export_shift_overrides",
                     "--salon-id", str(self.salon.id),
                     "--is-on-only", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(self.salon, is_off=False))

    def test_is_off_and_is_on_only_conflict(self):
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides",
                         salon_id=self.salon.id, is_off_only=True,
                         is_on_only=True, stdout=io.StringIO())

    def test_no_is_off_flag_is_default(self):
        self._off()
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(self.salon, is_off=None))
        self.assertEqual(out.getvalue(),
                         export_shift_overrides_csv(self.salon))

    def test_is_off_composes_with_staff_and_window(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        ShiftOverride.objects.create(
            staff_member=eve, date=datetime.date(2026, 11, 7),
            is_off=True)
        self._off()
        out = io.StringIO()
        call_command("export_shift_overrides",
                     salon_id=self.salon.id,
                     staff_member_id=self.staff.id,
                     start_date=datetime.date(2026, 11, 1),
                     end_date=datetime.date(2026, 11, 30),
                     is_off_only=True, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_shift_overrides_csv(
                self.salon, staff_member=self.staff,
                start_date=datetime.date(2026, 11, 1),
                end_date=datetime.date(2026, 11, 30), is_off=True))
        self.assertIn("Dana", out.getvalue())
        self.assertNotIn("Eve", out.getvalue())
        self.assertNotIn("2026-10-31", out.getvalue())

    def test_unknown_salon_required_id_and_unwritable(self):
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides",
                         salon_id=999999, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_shift_overrides",
                         salon_id=self.salon.id,
                         output="/nonexistent-dir/out.csv",
                         stdout=io.StringIO())
