import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.break_totals_export import (
    BREAK_TOTALS_EXPORT_FIELDNAMES,
    break_totals_rows,
    export_break_totals_csv,
)
from bookings.models import Break
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class BreakTotalsExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        Break.objects.create(
            staff_member=self.staff, start=at(DAY, 12),
            end=at(DAY, 12, 30), paid=True)
        Break.objects.create(
            staff_member=self.staff, start=at(DAY, 13),
            end=at(DAY, 14), paid=False)

    def test_rows_match_service_totals(self):
        rows = break_totals_rows(self.salon, DAY)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(list(row.keys()), BREAK_TOTALS_EXPORT_FIELDNAMES)
        self.assertEqual(row["salon_id"], self.salon.pk)
        self.assertEqual(row["start_date"], DAY.isoformat())
        self.assertEqual(row["staff_name"], "Stylist One")
        self.assertEqual((row["break_count"], row["total_break_minutes"]), (2, 90))
        self.assertEqual((row["paid_break_count"], row["paid_minutes"]), (1, 30))
        self.assertEqual((row["unpaid_break_count"], row["unpaid_minutes"]), (1, 60))

    def test_csv_header_and_row(self):
        text = export_break_totals_csv(self.salon, DAY)
        lines = text.splitlines()
        self.assertEqual(lines[0], ",".join(BREAK_TOTALS_EXPORT_FIELDNAMES))
        self.assertEqual(len(lines), 2)
        self.assertIn("Stylist One", lines[1])
        self.assertIn(",2,90,1,30,1,60", lines[1])
        self.assertTrue(text.endswith("\n"))

    def test_empty_range_csv_is_header_only(self):
        empty_day = DAY + datetime.timedelta(days=7)
        self.assertEqual(break_totals_rows(self.salon, empty_day), [])
        text = export_break_totals_csv(self.salon, empty_day)
        self.assertEqual(text, ",".join(BREAK_TOTALS_EXPORT_FIELDNAMES) + "\n")

    def test_command_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_break_totals", salon_id=self.salon.pk,
                     date_from=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_break_totals_csv(self.salon, DAY, None))

    def test_command_output_file_and_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "breaks.csv")
            call_command("export_break_totals", salon_id=self.salon.pk,
                         date_from=DAY, date_to=DAY, output=path,
                         stdout=io.StringIO())
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(fh.read(),
                                 export_break_totals_csv(self.salon, DAY, DAY))
        with self.assertRaises(CommandError):
            call_command("export_break_totals", salon_id=self.salon.pk + 1000,
                         date_from=DAY, stdout=io.StringIO())
        with self.assertRaises(CommandError):
            call_command("export_break_totals", salon_id=self.salon.pk,
                         stdout=io.StringIO())
