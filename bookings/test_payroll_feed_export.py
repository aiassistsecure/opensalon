import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Break
from bookings.payroll_feed_export import (
    PAYROLL_FEED_EXPORT_FIELDNAMES,
    export_payroll_feed_csv,
    payroll_feed_rows,
)
from saloncore.models import Salon
from team.models import AttendanceRecord, RosterPattern, StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class PayrollFeedExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=datetime.time(9), end_time=datetime.time(17))
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_in", recorded_at=at(DAY, 9))
        AttendanceRecord.objects.create(
            staff_member=self.staff, event_type="check_out", recorded_at=at(DAY, 17))
        Break.objects.create(staff_member=self.staff, start=at(DAY, 12),
                             end=at(DAY, 12, 30), paid=True)

    def test_rows_and_csv_match_service(self):
        rows = payroll_feed_rows(self.salon, DAY, DAY)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(list(row.keys()), PAYROLL_FEED_EXPORT_FIELDNAMES)
        self.assertEqual((row["salon_id"], row["start_date"], row["end_date"]),
                         (self.salon.pk, DAY.isoformat(), DAY.isoformat()))
        self.assertEqual((row["rostered_minutes"], row["actual_minutes"]), (480, 480))
        self.assertEqual((row["paid_minutes"], row["unpaid_minutes"]), (30, 0))
        text = export_payroll_feed_csv(self.salon, DAY, DAY)
        lines = text.splitlines()
        self.assertEqual(lines[0], ",".join(PAYROLL_FEED_EXPORT_FIELDNAMES))
        self.assertEqual(len(lines), 2)
        self.assertTrue(text.endswith("\n"))

    def test_command_stdout_file_and_errors(self):
        out = io.StringIO()
        call_command("export_payroll_feed", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_payroll_feed_csv(self.salon, DAY, DAY))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "payroll.csv")
            call_command("export_payroll_feed", salon_id=self.salon.pk,
                         start_date=DAY, end_date=DAY, output=path,
                         stdout=io.StringIO())
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(fh.read(), out.getvalue())
        for kwargs in (
            dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY),
            dict(salon_id=self.salon.pk, end_date=DAY),
            dict(salon_id=self.salon.pk, start_date=DAY),
            dict(salon_id=self.salon.pk, start_date=DAY,
                 end_date=DAY - datetime.timedelta(days=1)),
        ):
            with self.assertRaises(CommandError):
                call_command("export_payroll_feed", stdout=io.StringIO(), **kwargs)
