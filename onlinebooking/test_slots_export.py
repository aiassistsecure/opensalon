import csv
import datetime
import io

from django.test import TestCase

from onlinebooking.slots import available_slots
from onlinebooking.slots_export import (
    EXPORT_FIELDNAMES,
    export_slots,
    export_slots_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class SlotsExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Online Stylist", online_bookable=True
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _roster(self, staff=None, weekday=0, start=(9, 0), end=(11, 0), **kw):
        return RosterPattern.objects.create(
            staff_member=staff or self.staff, weekday=weekday,
            start_time=datetime.time(*start), end_time=datetime.time(*end), **kw,
        )

    def test_csv_header_columns_and_rows_match_service_output(self):
        self._roster()  # Mondays 09:00-11:00; 60 min -> 5 starts
        text = export_slots_csv(self.salon, self.staff, MONDAY, 60)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        expected = available_slots(self.staff, MONDAY, 60)
        self.assertEqual(len(parsed), len(expected))
        self.assertEqual(
            [r["slot_start"] for r in parsed],
            [slot.isoformat() for slot in expected],
        )
        row = parsed[0]
        self.assertEqual(row["salon_id"], str(self.salon.pk))
        self.assertEqual(row["staff_member_id"], str(self.staff.pk))
        self.assertEqual(row["staff_name"], "Online Stylist")
        self.assertEqual(row["date"], MONDAY.isoformat())
        self.assertEqual(row["slot_start"], at(MONDAY, 9).isoformat())
        # Dict export agrees with CSV and the service verbatim.
        records = export_slots(self.salon, self.staff, MONDAY, 60)
        self.assertEqual(list(records[0].keys()), EXPORT_FIELDNAMES)
        self.assertEqual(
            [r["slot_start"] for r in records],
            [slot.isoformat() for slot in expected],
        )

    def test_accepts_service_object_as_duration(self):
        self._roster()
        records = export_slots(self.salon, self.staff, MONDAY, self.service)
        self.assertEqual(
            [r["slot_start"] for r in records],
            [s.isoformat() for s in available_slots(self.staff, MONDAY, self.service)],
        )

    def test_toggle_off_staff_exports_no_rows(self):
        offline = StaffMember.objects.create(
            salon=self.salon, display_name="Offline", online_bookable=False)
        self._roster(staff=offline)
        self.assertEqual(export_slots(self.salon, offline, MONDAY, 45), [])
        text = export_slots_csv(self.salon, offline, MONDAY, 45)
        self.assertEqual(
            text.strip().splitlines(), [",".join(EXPORT_FIELDNAMES)])

    def test_salon_isolation(self):
        other_salon = Salon.objects.create(name="Other", timezone="UTC")
        other = StaffMember.objects.create(
            salon=other_salon, display_name="Other Stylist",
            online_bookable=True)
        self._roster()
        self._roster(staff=other)
        # This salon's staff exports; the other salon's staff does not.
        records = export_slots(self.salon, self.staff, MONDAY, 60)
        self.assertTrue(records)
        self.assertTrue(all(r["salon_id"] == self.salon.pk for r in records))
        self.assertEqual(export_slots(self.salon, other, MONDAY, 60), [])
        self.assertEqual(export_slots(other_salon, self.staff, MONDAY, 60), [])
        other_records = export_slots(other_salon, other, MONDAY, 60)
        self.assertTrue(other_records)
        self.assertTrue(
            all(r["salon_id"] == other_salon.pk for r in other_records))

    def test_empty_exports_header_only(self):
        # Bookable but unrostered staff has no slots.
        self.assertEqual(export_slots(self.salon, self.staff, MONDAY, 60), [])
        self.assertEqual(export_slots(None, self.staff, MONDAY, 60), [])
        self.assertEqual(export_slots(self.salon, None, MONDAY, 60), [])
        for salon, staff in ((self.salon, self.staff), (None, self.staff),
                             (self.salon, None)):
            text = export_slots_csv(salon, staff, MONDAY, 60)
            self.assertEqual(
                text.strip().splitlines(), [",".join(EXPORT_FIELDNAMES)])
