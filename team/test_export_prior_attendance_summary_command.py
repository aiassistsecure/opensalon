"""Tests for export_prior_attendance_summary --format json|csv."""
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from saloncore.models import Salon
from team.models import AttendanceRecord, StaffMember
from team.prior_attendance_summary_export import (
    export_prior_attendance_summary,
    export_prior_attendance_summary_csv,
)

DAY = datetime.date(2026, 11, 2)
PRIOR_DAY = datetime.date(2026, 11, 1)
NEXT = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class ExportPriorAttendanceSummaryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self._session(self.staff, PRIOR_DAY)
        self._session(self.other, PRIOR_DAY, end=(13, 0))
        self._session(self.staff, DAY, end=(13, 0))
        self._session(self.other, DAY, end=None)

    def _session(self, staff, day, start=(9, 0), end=(17, 0)):
        AttendanceRecord.objects.create(
            staff_member=staff, event_type="check_in",
            recorded_at=at(day, *start))
        if end is not None:
            AttendanceRecord.objects.create(
                staff_member=staff, event_type="check_out",
                recorded_at=at(day, *end))

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_prior_attendance_summary",
                     salon_id=self.salon.pk, start_date=DAY,
                     end_date=DAY, stdout=out, **kwargs)
        return out.getvalue()

    def test_default_format_is_csv_and_byte_identical(self):
        self.assertEqual(
            self._call(),
            export_prior_attendance_summary_csv(self.salon, DAY, DAY))

    def test_explicit_csv_matches_service(self):
        self.assertEqual(
            self._call(format="csv"),
            export_prior_attendance_summary_csv(self.salon, DAY, DAY))

    def test_csv_cli_spelling_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_attendance_summary",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(),
                     "--end-date", DAY.isoformat(),
                     "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_attendance_summary_csv(self.salon, DAY, DAY))

    def test_json_parses_and_equals_dict_service_rows(self):
        rows = export_prior_attendance_summary(self.salon, DAY, DAY)
        text = self._call(format="json")
        self.assertEqual(json.loads(text), rows)
        self.assertEqual(
            text, json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_cli_spelling_matches_dict_service(self):
        out = io.StringIO()
        call_command("export_prior_attendance_summary",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(),
                     "--end-date", DAY.isoformat(),
                     "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_prior_attendance_summary(self.salon, DAY, DAY))

    def test_json_composes_with_date_window(self):
        rows = export_prior_attendance_summary(self.salon, DAY, NEXT)
        out = io.StringIO()
        call_command("export_prior_attendance_summary",
                     salon_id=self.salon.pk, start_date=DAY,
                     end_date=NEXT, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        # The same window in CSV also matches its service verbatim.
        out = io.StringIO()
        call_command("export_prior_attendance_summary",
                     salon_id=self.salon.pk, start_date=DAY,
                     end_date=NEXT, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_attendance_summary_csv(self.salon, DAY, NEXT))

    def test_json_output_file_matches_dict_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.json")
            out = io.StringIO()
            call_command("export_prior_attendance_summary",
                         salon_id=self.salon.pk, start_date=DAY,
                         end_date=DAY, format="json", output=path,
                         stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(
            json.loads(written),
            export_prior_attendance_summary(self.salon, DAY, DAY))
        self.assertEqual(
            written,
            json.dumps(export_prior_attendance_summary(self.salon, DAY, DAY),
                       indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_csv_output_file_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_attendance_summary",
                         salon_id=self.salon.pk, start_date="2026-11-02",
                         end_date="2026-11-02", output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(),
                    export_prior_attendance_summary_csv(self.salon, DAY, DAY))

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_attendance_summary",
                         "--salon-id", str(self.salon.pk),
                         "--start-date", DAY.isoformat(),
                         "--end-date", DAY.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_json_unknown_salon_and_reversed_range_raise(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_attendance_summary",
                         salon_id=self.salon.pk + 1000, start_date=DAY,
                         end_date=DAY, format="json", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_attendance_summary",
                         salon_id=self.salon.pk, start_date=NEXT,
                         end_date=DAY, format="json", stdout=io.StringIO())
