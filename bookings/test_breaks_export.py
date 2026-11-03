import datetime
import io
import os
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.breaks import breaks, list_breaks
from bookings.breaks_export import (
    BREAK_EXPORT_FIELDNAMES,
    EXPORT_FIELDNAMES,
    breaks_rows,
    export_breaks,
    export_breaks_csv,
)
from bookings.models import Break
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class BreaksExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.b1 = Break.objects.create(
            staff_member=self.staff, start=at(DAY, 12),
            end=at(DAY, 12, 30), paid=True)
        self.b2 = Break.objects.create(
            staff_member=self.staff, start=at(DAY, 13),
            end=at(DAY, 14), paid=False)

    def test_content_verbatim_not_aggregated(self):
        rows = export_breaks(self.salon, DAY)
        # Two stored breaks for one staff member stay two rows,
        # never the single aggregate row of break_totals.
        self.assertEqual(len(rows), 2)
        self.assertEqual(EXPORT_FIELDNAMES, BREAK_EXPORT_FIELDNAMES)
        self.assertEqual(list(rows[0].keys()), BREAK_EXPORT_FIELDNAMES)
        self.assertEqual(rows[0], {
            "id": self.b1.pk, "salon_id": self.salon.pk,
            "staff_member_id": self.staff.pk, "staff_name": "Stylist One",
            "start": at(DAY, 12).isoformat(),
            "end": at(DAY, 12, 30).isoformat(), "paid": True})
        self.assertEqual(rows[1]["id"], self.b2.pk)
        self.assertEqual(rows[1]["paid"], False)
        records = breaks(self.salon, DAY)
        self.assertEqual([r.id for r in records], [self.b1.pk, self.b2.pk])
        self.assertIs(list_breaks, breaks)

    def test_csv_header_and_rows(self):
        text = export_breaks_csv(self.salon, DAY)
        lines = text.splitlines()
        self.assertEqual(lines[0], ",".join(BREAK_EXPORT_FIELDNAMES))
        self.assertEqual(len(lines), 3)
        self.assertIn("Stylist One", lines[1])
        self.assertTrue(lines[1].endswith(",True"))
        self.assertTrue(lines[2].endswith(",False"))
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(breaks_rows(self.salon, DAY), export_breaks(self.salon, DAY))

    def test_date_range_and_no_range(self):
        Break.objects.create(
            staff_member=self.staff, start=at(NEXT, 12),
            end=at(NEXT, 12, 45), paid=True)
        self.assertEqual(len(export_breaks(self.salon)), 3)
        self.assertEqual(len(export_breaks(self.salon, DAY, NEXT)), 3)
        self.assertEqual(len(export_breaks(self.salon, NEXT)), 1)
        self.assertEqual(export_breaks(self.salon, NEXT, DAY), [])

    def test_salon_scoping(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        other_staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        Break.objects.create(
            staff_member=other_staff, start=at(DAY, 12),
            end=at(DAY, 13), paid=True)
        self.assertEqual(len(export_breaks(self.salon, DAY)), 2)
        self.assertEqual(len(export_breaks(other, DAY)), 1)
        self.assertEqual(export_breaks(None, DAY), [])

    def test_empty_case(self):
        empty_day = DAY + datetime.timedelta(days=7)
        self.assertEqual(export_breaks(self.salon, empty_day), [])
        self.assertEqual(breaks(self.salon, empty_day), ())
        self.assertEqual(
            export_breaks_csv(self.salon, empty_day),
            ",".join(BREAK_EXPORT_FIELDNAMES) + "\n")

    def test_read_only(self):
        before = (Break.objects.count(), StaffMember.objects.count(),
                  Salon.objects.count())
        export_breaks(self.salon)
        export_breaks_csv(self.salon, DAY)
        breaks(self.salon, DAY)
        self.assertEqual(
            (Break.objects.count(), StaffMember.objects.count(),
             Salon.objects.count()), before)

    def test_command_stdout_matches_service(self):
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk,
                     date_from=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_breaks_csv(self.salon, DAY, None))
        out = io.StringIO()
        call_command("export_breaks", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_breaks_csv(self.salon, None, None))

    def test_command_output_file_and_unknown_salon(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "breaks.csv")
            call_command("export_breaks", salon_id=self.salon.pk,
                         date_from=DAY, date_to=DAY, output=path,
                         stdout=io.StringIO())
            with open(path, encoding="utf-8", newline="") as fh:
                self.assertEqual(fh.read(), export_breaks_csv(self.salon, DAY, DAY))
        with self.assertRaises(CommandError):
            call_command("export_breaks", salon_id=self.salon.pk + 1000,
                         stdout=io.StringIO())
