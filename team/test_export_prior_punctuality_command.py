"""Tests for export_prior_punctuality --format json|csv."""
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from saloncore.models import Salon
from team.models import AttendanceRecord, RosterPattern, StaffMember
from team.prior_punctuality_export import (
    export_prior_punctuality,
    export_prior_punctuality_csv,
)

DAY = datetime.date(2026, 11, 2)  # Monday (current)
PRIOR_DAY = datetime.date(2026, 11, 1)  # Sunday (prior)
NEXT = datetime.date(2026, 11, 3)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class ExportPriorPunctualityCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        self.monday_only = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Three")
        for member in (self.staff, self.other):
            for weekday in range(7):
                RosterPattern.objects.create(
                    staff_member=member, weekday=weekday,
                    start_time=datetime.time(9, 0),
                    end_time=datetime.time(17, 0))
        RosterPattern.objects.create(
            staff_member=self.monday_only, weekday=0,
            start_time=datetime.time(9, 0), end_time=datetime.time(17, 0))
        self._book()

    def _check_in(self, staff, day, hour, minute=0):
        AttendanceRecord.objects.create(
            staff_member=staff, event_type="check_in",
            recorded_at=at(day, hour, minute))

    def _book(self):
        self._check_in(self.staff, PRIOR_DAY, 9, 0)   # prior: on time
        self._check_in(self.other, PRIOR_DAY, 9, 30)  # prior: late 30
        self._check_in(self.staff, DAY, 9, 10)        # current: late 10
        self._check_in(self.monday_only, DAY, 9, 0)   # current: on time

    def _call(self, **kwargs):
        out = io.StringIO()
        call_command("export_prior_punctuality",
                     salon_id=self.salon.pk, start_date=DAY,
                     end_date=DAY, stdout=out, **kwargs)
        return out.getvalue()

    def test_default_format_is_csv_and_byte_identical(self):
        self.assertEqual(
            self._call(), export_prior_punctuality_csv(self.salon, DAY, DAY))

    def test_explicit_csv_matches_service(self):
        self.assertEqual(
            self._call(format="csv"),
            export_prior_punctuality_csv(self.salon, DAY, DAY))

    def test_csv_cli_spelling_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_punctuality",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(),
                     "--end-date", DAY.isoformat(),
                     "--format", "csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_punctuality_csv(self.salon, DAY, DAY))

    def test_json_parses_and_equals_dict_service_rows(self):
        rows = export_prior_punctuality(self.salon, DAY, DAY)
        text = self._call(format="json")
        self.assertEqual(json.loads(text), rows)
        self.assertEqual(
            text, json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_cli_spelling_matches_dict_service(self):
        out = io.StringIO()
        call_command("export_prior_punctuality",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(),
                     "--end-date", DAY.isoformat(),
                     "--format", "json", stdout=out)
        self.assertEqual(
            json.loads(out.getvalue()),
            export_prior_punctuality(self.salon, DAY, DAY))

    def test_json_composes_with_date_window(self):
        rows = export_prior_punctuality(self.salon, DAY, NEXT)
        out = io.StringIO()
        call_command("export_prior_punctuality",
                     salon_id=self.salon.pk, start_date=DAY,
                     end_date=NEXT, format="json", stdout=out)
        self.assertEqual(json.loads(out.getvalue()), rows)
        out = io.StringIO()
        call_command("export_prior_punctuality",
                     salon_id=self.salon.pk, start_date=DAY,
                     end_date=NEXT, format="csv", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_prior_punctuality_csv(self.salon, DAY, NEXT))

    def test_json_output_file_matches_dict_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.json")
            out = io.StringIO()
            call_command("export_prior_punctuality",
                         salon_id=self.salon.pk, start_date=DAY,
                         end_date=DAY, format="json", output=path,
                         stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(
            json.loads(written),
            export_prior_punctuality(self.salon, DAY, DAY))
        self.assertEqual(
            written,
            json.dumps(export_prior_punctuality(self.salon, DAY, DAY),
                       indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_csv_output_file_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.csv")
            call_command("export_prior_punctuality",
                         salon_id=self.salon.pk,
                         start_date="2026-11-02", end_date="2026-11-02",
                         output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(
                    fh.read(),
                    export_prior_punctuality_csv(self.salon, DAY, DAY))

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")

    def test_invalid_format_via_cli_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_punctuality",
                         "--salon-id", str(self.salon.pk),
                         "--start-date", DAY.isoformat(),
                         "--end-date", DAY.isoformat(),
                         "--format", "xml", stdout=io.StringIO())

    def test_json_unknown_salon_and_reversed_range_raise(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_punctuality",
                         salon_id=self.salon.pk + 1000, start_date=DAY,
                         end_date=DAY, format="json", stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_prior_punctuality",
                         salon_id=self.salon.pk, start_date=NEXT,
                         end_date=DAY, format="json", stdout=io.StringIO())
