"""Tests for --format on the export_prior_payroll_feed command.

CSV (default) must be byte-identical to the service; JSON must
parse and equal prior_payroll_feed_rows for the same arguments
(serialised via DjangoJSONEncoder, so Decimal percent changes
become strings), and CSV/JSON rows must agree. Fixtures are
tiny synthetic records.
"""
import csv
import datetime
import io
import json
import os
import tempfile

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Break
from bookings.prior_payroll_feed_export import (
    export_prior_payroll_feed_csv,
    prior_payroll_feed_rows,
)
from saloncore.models import Salon
from team.models import AttendanceRecord, RosterPattern, StaffMember

DAY = datetime.date(2026, 11, 2)
PRIOR_DAY = DAY - datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


def _expected_json(rows):
    return json.loads(json.dumps(rows, cls=DjangoJSONEncoder))


class ExportPriorPayrollFeedFormatCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist Two")
        for staff, wd, span in ((self.staff, 0, (9, 17)), (self.staff, 6, (9, 13)), (self.staff2, 0, (10, 14))):
            RosterPattern.objects.create(
                staff_member=staff, weekday=wd,
                start_time=datetime.time(span[0]), end_time=datetime.time(span[1]))
        self._session(self.staff, PRIOR_DAY, (9, 0), (13, 0))
        self._break(self.staff, PRIOR_DAY, 12, 30, paid=True)
        self._session(self.staff, DAY, (9, 0), (17, 30))
        self._session(self.staff2, DAY, (10, 0), None)
        self._break(self.staff, DAY, 12, 45, paid=True)
        self._break(self.staff, DAY, 13, 15, paid=False)
        self._break(self.staff2, DAY, 12, 20, paid=False)

    def _session(self, staff, day, start, end):
        AttendanceRecord.objects.create(
            staff_member=staff, event_type="check_in", recorded_at=at(day, *start))
        if end is not None:
            AttendanceRecord.objects.create(
                staff_member=staff, event_type="check_out", recorded_at=at(day, *end))

    def _break(self, staff, day, hour, minutes, paid):
        start = at(day, hour)
        Break.objects.create(staff_member=staff, start=start,
                             end=start + datetime.timedelta(minutes=minutes), paid=paid)

    def test_default_format_is_csv_byte_identical(self):
        out = io.StringIO()
        call_command("export_prior_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_payroll_feed_csv(self.salon, DAY, DAY))

    def test_explicit_csv_matches_service(self):
        out = io.StringIO()
        call_command("export_prior_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_payroll_feed_csv(self.salon, DAY, DAY))
        out = io.StringIO()
        call_command("export_prior_payroll_feed", "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_payroll_feed_csv(self.salon, DAY, DAY))

    def test_json_parses_and_equals_rows(self):
        out = io.StringIO()
        call_command("export_prior_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        rows = prior_payroll_feed_rows(self.salon, DAY, DAY)
        self.assertEqual(json.loads(out.getvalue()), _expected_json(rows))
        self.assertEqual(out.getvalue(),
                         json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_csv_json_row_agreement(self):
        csv_out, json_out = io.StringIO(), io.StringIO()
        call_command("export_prior_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=csv_out)
        call_command("export_prior_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=json_out)
        csv_rows = list(csv.DictReader(io.StringIO(csv_out.getvalue())))
        json_rows = json.loads(json_out.getvalue())
        self.assertEqual(len(csv_rows), len(json_rows))
        self.assertEqual(len(json_rows), 3)
        for crow, jrow in zip(csv_rows, json_rows):
            self.assertEqual(list(jrow.keys()), list(crow.keys()))
            for key, val in jrow.items():
                self.assertEqual(crow[key], "" if val is None else str(val))

    def test_json_empty(self):
        empty = Salon.objects.create(name="Empty Salon", timezone="UTC")
        out = io.StringIO()
        call_command("export_prior_payroll_feed", salon_id=empty.pk,
                     start_date=DAY, end_date=DAY, format="json", stdout=out)
        rows = prior_payroll_feed_rows(empty, DAY, DAY)
        self.assertEqual(len(rows), 1)  # salon total row only
        self.assertEqual(json.loads(out.getvalue()), _expected_json(rows))
        self.assertEqual(out.getvalue(),
                         json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_filters_compose(self):
        out = io.StringIO()
        call_command("export_prior_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, staff_member=self.staff.pk,
                     format="json", stdout=out)
        rows = prior_payroll_feed_rows(self.salon, DAY, DAY,
                                       staff_member=self.staff)
        self.assertEqual(json.loads(out.getvalue()), _expected_json(rows))

    def test_json_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_payroll.json")
            call_command("export_prior_payroll_feed", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="json",
                         output=path, stdout=io.StringIO())
            with open(path, encoding="utf-8", newline="") as fh:
                written = fh.read()
        rows = prior_payroll_feed_rows(self.salon, DAY, DAY)
        self.assertEqual(written,
                         json.dumps(rows, indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_unknown_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_payroll_feed", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, format="xml",
                         stdout=io.StringIO())
        with self.assertRaises((CommandError, SystemExit)):
            call_command("export_prior_payroll_feed", "--salon-id", str(self.salon.pk),
                         "--start-date", DAY.isoformat(),
                         "--end-date", DAY.isoformat(), "--format", "xml",
                         stdout=io.StringIO())
