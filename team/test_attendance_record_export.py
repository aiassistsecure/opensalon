"""Attendance record export: stored AttendanceRecord rows verbatim."""
import csv
import datetime
import io

from django.test import TestCase

from saloncore.models import Salon
from team.attendance_record_export import (
    ATTENDANCE_RECORD_EXPORT_FIELDNAMES,
    EXPORT_FIELDNAMES,
    attendance_records_csv,
    export_attendance_records,
    export_attendance_records_csv,
)
from team.models import AttendanceRecord, StaffMember

UTC = datetime.timezone.utc
DAY = datetime.date(2026, 10, 31)


def at(hour, minute=0):
    return datetime.datetime.combine(
        DAY, datetime.time(hour, minute), tzinfo=UTC)


class AttendanceRecordExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Record Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other", timezone="UTC")
        # PIN and email are set so the hygiene test is meaningful.
        self.dana = StaffMember.objects.create(
            salon=self.salon, display_name="Dana",
            pin="1234", email="dana@example.com")
        self.other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Dana")

    def _in(self, staff=None, when=None, note=""):
        return AttendanceRecord.objects.create(
            staff_member=staff or self.dana, event_type="check_in",
            recorded_at=when or at(9), note=note)

    def _out(self, staff=None, when=None, note=""):
        return AttendanceRecord.objects.create(
            staff_member=staff or self.dana, event_type="check_out",
            recorded_at=when or at(17), note=note)

    def test_header_and_dict_keys(self):
        self._in()
        text = export_attendance_records_csv(self.salon)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], ATTENDANCE_RECORD_EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES,
                         ATTENDANCE_RECORD_EXPORT_FIELDNAMES)
        records = export_attendance_records(self.salon)
        self.assertEqual(len(records), 1)
        self.assertEqual(list(records[0].keys()),
                         ATTENDANCE_RECORD_EXPORT_FIELDNAMES)
        self.assertIs(attendance_records_csv,
                      export_attendance_records_csv)

    def test_check_in_shape_verbatim(self):
        rec = self._in(note="front desk")
        records = export_attendance_records(self.salon)
        self.assertEqual(records, [{
            "id": rec.pk, "salon_id": self.salon.pk,
            "staff_member_id": self.dana.pk, "staff_name": "Dana",
            "event_type": "check_in",
            "recorded_at": "2026-10-31T09:00:00+00:00",
            "note": "front desk"}])

    def test_check_out_shape_verbatim_empty_note(self):
        rec = self._out()
        records = export_attendance_records(self.salon)
        self.assertEqual(records, [{
            "id": rec.pk, "salon_id": self.salon.pk,
            "staff_member_id": self.dana.pk, "staff_name": "Dana",
            "event_type": "check_out",
            "recorded_at": "2026-10-31T17:00:00+00:00",
            "note": ""}])
        parsed = list(csv.DictReader(io.StringIO(
            export_attendance_records_csv(self.salon))))
        self.assertEqual(parsed[0]["event_type"], "check_out")
        self.assertEqual(parsed[0]["note"], "")

    def test_model_ordering_latest_first_then_id(self):
        first = self._in(when=at(9))
        out = self._out(when=at(17))
        tie = self._in(when=at(17), note="again")
        records = export_attendance_records(self.salon)
        self.assertEqual([r["id"] for r in records],
                         [tie.pk, out.pk, first.pk])

    def test_unpaired_rows_exported_verbatim_not_sessions(self):
        self._in()
        self._in(when=at(10))
        records = export_attendance_records(self.salon)
        self.assertEqual(len(records), 2)
        self.assertTrue(
            all(r["event_type"] == "check_in" for r in records))

    def test_salon_scoping_and_empty(self):
        self._in()
        self._in(staff=self.other_staff)
        self.assertEqual(len(export_attendance_records(self.salon)), 1)
        self.assertEqual(
            len(export_attendance_records(self.other_salon)), 1)
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_attendance_records(empty), [])
        self.assertEqual(
            export_attendance_records_csv(empty),
            ",".join(ATTENDANCE_RECORD_EXPORT_FIELDNAMES) + "\n")

    def test_no_pin_or_email_anywhere(self):
        self._in()
        self.assertNotIn("pin", ATTENDANCE_RECORD_EXPORT_FIELDNAMES)
        self.assertNotIn("email", ATTENDANCE_RECORD_EXPORT_FIELDNAMES)
        text = export_attendance_records_csv(self.salon)
        self.assertNotIn("1234", text)
        self.assertNotIn("dana@example.com", text)

    def test_read_only(self):
        self._in()
        self._out()
        before = AttendanceRecord.objects.count()
        export_attendance_records(self.salon)
        export_attendance_records_csv(self.salon)
        self.assertEqual(AttendanceRecord.objects.count(), before)
