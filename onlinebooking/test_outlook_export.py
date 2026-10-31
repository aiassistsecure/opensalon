import csv
import datetime
import io

from django.test import TestCase

from onlinebooking.outlook import availability_outlook
from onlinebooking.outlook_export import (
    EXPORT_FIELDNAMES,
    export_outlook,
    export_outlook_csv,
)
from saloncore.models import Salon
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class OutlookExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True
        )

    def _roster(self, staff=None, weekday=0, start=(9, 0), end=(11, 0), **kw):
        return RosterPattern.objects.create(
            staff_member=staff or self.staff, weekday=weekday,
            start_time=datetime.time(*start), end_time=datetime.time(*end), **kw,
        )

    def test_csv_header_and_row_for_rostered_bookable_staff(self):
        self._roster()  # Mondays 09:00-11:00; 60 min -> 5 starts
        text = export_outlook_csv(self.salon, 60, days=1, start_date=MONDAY)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(parsed), 1)
        row = parsed[0]
        self.assertEqual(row["salon_id"], str(self.salon.pk))
        self.assertEqual(row["staff_member_id"], str(self.staff.pk))
        self.assertEqual(row["staff_name"], "Online Stylist")
        self.assertEqual(row["date"], MONDAY.isoformat())
        self.assertEqual(row["slot_count"], "5")
        self.assertEqual(row["first_slot"], at(MONDAY, 9).isoformat())
        self.assertEqual(row["last_slot"], at(MONDAY, 10).isoformat())
        self.assertEqual(
            row["slots"].split(";"),
            [at(MONDAY, 9, m).isoformat() for m in (0, 15, 30, 45)]
            + [at(MONDAY, 10).isoformat()],
        )
        # Dict export agrees with the CSV and the outlook service.
        records = export_outlook(self.salon, 60, days=1, start_date=MONDAY)
        self.assertEqual(list(records[0].keys()), EXPORT_FIELDNAMES)
        self.assertEqual(records[0]["slot_count"], 5)
        outlook = availability_outlook(
            self.salon, 60, days=1, start_date=MONDAY)
        self.assertEqual(records[0]["slot_count"], outlook[0].total_slots)

    def test_online_bookable_false_staff_excluded(self):
        offline = StaffMember.objects.create(
            salon=self.salon, display_name="Offline", online_bookable=False)
        self._roster()
        self._roster(staff=offline)
        records = export_outlook(self.salon, 60, days=1, start_date=MONDAY)
        self.assertEqual(
            [r["staff_member_id"] for r in records], [self.staff.pk])
        text = export_outlook_csv(self.salon, 60, days=1, start_date=MONDAY)
        self.assertNotIn("Offline", text)

    def test_salon_scoping(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        other = StaffMember.objects.create(
            salon=other_salon, display_name="Other Stylist",
            online_bookable=True)
        self._roster()
        self._roster(staff=other)
        records = export_outlook(self.salon, 60, days=1, start_date=MONDAY)
        self.assertEqual(
            [r["staff_member_id"] for r in records], [self.staff.pk])
        self.assertTrue(all(r["salon_id"] == self.salon.pk for r in records))
        other_records = export_outlook(
            other_salon, 60, days=1, start_date=MONDAY)
        self.assertEqual(
            [r["staff_member_id"] for r in other_records], [other.pk])

    def test_empty_exports_header_only(self):
        empty_salon = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_outlook(empty_salon, 60, start_date=MONDAY), [])
        self.assertEqual(export_outlook(None, 60, start_date=MONDAY), [])
        for salon in (empty_salon, None):
            text = export_outlook_csv(salon, 60, start_date=MONDAY)
            self.assertEqual(
                text.strip().splitlines(), [",".join(EXPORT_FIELDNAMES)])

    def test_bookable_unrostered_staff_exports_zero_row(self):
        records = export_outlook(self.salon, 60, days=1, start_date=MONDAY)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["slot_count"], 0)
        self.assertIsNone(records[0]["first_slot"])
        self.assertIsNone(records[0]["last_slot"])
        self.assertEqual(records[0]["slots"], "")
