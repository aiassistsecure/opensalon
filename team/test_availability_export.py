import csv
import datetime
import io

from django.test import TestCase

from saloncore.models import Salon
from team.availability_export import (
    AVAILABILITY_EXPORT_FIELDNAMES,
    EXPORT_FIELDNAMES,
    availability_csv,
    export_availability,
    export_availability_csv,
    export_roster_availability,
    export_roster_availability_csv,
    export_salon_roster,
    export_salon_roster_csv,
    roster_availability_csv,
    salon_roster_csv,
)
from team.models import RosterPattern, StaffMember

MONDAY = datetime.date(2026, 11, 2)  # a Monday
TUESDAY = datetime.date(2026, 11, 3)


class SalonRosterExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.offline = StaffMember.objects.create(
            salon=self.salon, display_name="Offline Two",
            online_bookable=False)

    def _pattern(self, staff=None, weekday=0, start=(9, 0), end=(17, 0),
                 **kw):
        return RosterPattern.objects.create(
            staff_member=staff or self.staff, weekday=weekday,
            start_time=datetime.time(*start),
            end_time=datetime.time(*end), **kw)

    def test_header_and_dict_keys(self):
        self._pattern()
        text = export_salon_roster_csv(self.salon, MONDAY)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], AVAILABILITY_EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, AVAILABILITY_EXPORT_FIELDNAMES)
        for record in export_salon_roster(self.salon, MONDAY):
            self.assertEqual(
                list(record.keys()), AVAILABILITY_EXPORT_FIELDNAMES)
        self.assertIs(salon_roster_csv, export_salon_roster_csv)
        self.assertIs(availability_csv, export_salon_roster_csv)
        self.assertIs(export_availability, export_salon_roster)
        self.assertIs(export_availability_csv, export_salon_roster_csv)

    def test_row_fields_from_service_structure(self):
        self._pattern(weekday=0, start=(9, 0), end=(17, 0))
        records = export_salon_roster(self.salon, MONDAY)
        monday = [r for r in records
                  if r["staff_member_id"] == self.staff.pk]
        self.assertEqual(monday, [{
            "salon_id": self.salon.pk,
            "staff_member_id": self.staff.pk,
            "staff_name": "Stylist One",
            "online_bookable": True,
            "date": "2026-11-02",
            "interval_start": "2026-11-02T09:00:00+00:00",
            "interval_end": "2026-11-02T17:00:00+00:00",
            "interval_minutes": 480,
            "total_minutes": 480,
            "is_working": True,
        }])

    def test_off_member_present_with_empty_interval_fields(self):
        self._pattern(weekday=0)
        records = export_salon_roster(self.salon, MONDAY)
        off = [r for r in records
               if r["staff_member_id"] == self.offline.pk]
        self.assertEqual(len(off), 1)
        self.assertIsNone(off[0]["interval_start"])
        self.assertIsNone(off[0]["interval_end"])
        self.assertIsNone(off[0]["interval_minutes"])
        self.assertEqual(off[0]["total_minutes"], 0)
        self.assertFalse(off[0]["is_working"])
        # A day nobody is rostered still lists every active member.
        tuesday = export_salon_roster(self.salon, TUESDAY)
        self.assertEqual(len(tuesday), 2)
        self.assertTrue(all(not r["is_working"] for r in tuesday))

    def test_split_shift_and_merging_come_from_service(self):
        self._pattern(weekday=0, start=(9, 0), end=(12, 0))
        self._pattern(weekday=0, start=(13, 0), end=(17, 0))
        self._pattern(weekday=0, start=(12, 0), end=(13, 0))
        records = [r for r in export_salon_roster(self.salon, MONDAY)
                   if r["staff_member_id"] == self.staff.pk]
        # Overlapping/touching patterns merge in the service, so
        # the export sees one merged interval, not three patterns.
        self.assertEqual(
            [(r["interval_start"], r["interval_end"],
              r["interval_minutes"]) for r in records],
            [("2026-11-02T09:00:00+00:00",
              "2026-11-02T17:00:00+00:00", 480)])

    def test_online_bookable_flag_separate_and_never_removes_intervals(self):
        self._pattern(staff=self.offline, weekday=0)
        monday = [r for r in export_salon_roster(self.salon, MONDAY)
                  if r["staff_member_id"] == self.offline.pk]
        self.assertEqual(len(monday), 1)
        self.assertFalse(monday[0]["online_bookable"])
        self.assertEqual(monday[0]["interval_minutes"], 480)
        self.assertTrue(monday[0]["is_working"])

    def test_ordering_and_inactive_exclusion_are_service_order(self):
        StaffMember.objects.create(
            salon=self.salon, display_name="Aaa Inactive", active=False)
        self._pattern()
        self._pattern(staff=self.offline)
        records = export_salon_roster(self.salon, MONDAY)
        self.assertEqual(
            [r["staff_name"] for r in records],
            ["Offline Two", "Stylist One"])

    def test_salon_timezone_comes_from_service(self):
        salon = Salon.objects.create(
            name="NY Salon", timezone="America/New_York")
        member = StaffMember.objects.create(
            salon=salon, display_name="NY One")
        self._pattern(staff=member, weekday=0)
        records = export_salon_roster(salon, MONDAY)
        self.assertEqual(
            records[0]["interval_start"], "2026-11-02T09:00:00-05:00")
        self.assertEqual(records[0]["salon_id"], salon.pk)

    def test_other_salon_not_included(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        outsider = StaffMember.objects.create(
            salon=other, display_name="Outsider")
        self._pattern(staff=outsider, weekday=0)
        names = [r["staff_name"]
                 for r in export_salon_roster(self.salon, MONDAY)]
        self.assertNotIn("Outsider", names)

    def test_csv_agrees_with_dict_export(self):
        self._pattern(weekday=0)
        records = export_salon_roster(self.salon, MONDAY)
        parsed = list(csv.DictReader(io.StringIO(
            export_salon_roster_csv(self.salon, MONDAY))))
        self.assertEqual(len(parsed), len(records))
        self.assertEqual(
            [p["staff_name"] for p in parsed],
            [r["staff_name"] for r in records])
        working = next(
            i for i, r in enumerate(records)
            if r["interval_minutes"] is not None)
        self.assertEqual(
            parsed[working]["interval_minutes"],
            str(records[working]["interval_minutes"]))
        self.assertEqual(
            parsed[working]["online_bookable"],
            str(records[working]["online_bookable"]))
        self.assertEqual(parsed[0]["interval_minutes"], "")
        self.assertTrue(export_salon_roster_csv(
            self.salon, MONDAY).endswith("\n"))

    def test_empty_salon_is_header_only(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_salon_roster(empty, MONDAY), [])
        self.assertEqual(
            export_salon_roster_csv(empty, MONDAY),
            ",".join(AVAILABILITY_EXPORT_FIELDNAMES) + "\n")

    def test_read_only(self):
        self._pattern()
        before = (StaffMember.objects.count(),
                  RosterPattern.objects.count())
        export_salon_roster(self.salon, MONDAY)
        export_salon_roster_csv(self.salon, MONDAY)
        export_roster_availability(self.staff, MONDAY)
        export_roster_availability_csv(self.staff, MONDAY)
        self.assertEqual(
            (StaffMember.objects.count(),
             RosterPattern.objects.count()), before)


class RosterAvailabilityExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")

    def _pattern(self, weekday=0, start=(9, 0), end=(17, 0), **kw):
        return RosterPattern.objects.create(
            staff_member=self.staff, weekday=weekday,
            start_time=datetime.time(*start),
            end_time=datetime.time(*end), **kw)

    def test_single_member_matches_salon_export_row(self):
        self._pattern()
        single = export_roster_availability(self.staff, MONDAY)
        from_salon = [r for r in export_salon_roster(self.salon, MONDAY)
                      if r["staff_member_id"] == self.staff.pk]
        self.assertEqual(single, from_salon)
        self.assertIs(
            roster_availability_csv, export_roster_availability_csv)

    def test_single_member_off_day_and_inactive(self):
        self._pattern(weekday=0)
        off = export_roster_availability(self.staff, TUESDAY)
        self.assertEqual(len(off), 1)
        self.assertIsNone(off[0]["interval_start"])
        self.assertFalse(off[0]["is_working"])
        inactive = StaffMember.objects.create(
            salon=self.salon, display_name="Gone", active=False)
        RosterPattern.objects.create(
            staff_member=inactive, weekday=0,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0))
        gone = export_roster_availability(inactive, MONDAY)
        self.assertEqual(len(gone), 1)
        self.assertIsNone(gone[0]["interval_start"])

    def test_single_member_csv_agrees_with_dict_export(self):
        self._pattern()
        records = export_roster_availability(self.staff, MONDAY)
        parsed = list(csv.DictReader(io.StringIO(
            export_roster_availability_csv(self.staff, MONDAY))))
        self.assertEqual(len(parsed), len(records))
        self.assertEqual(parsed[0]["staff_name"], "Stylist One")
        self.assertEqual(parsed[0]["interval_minutes"], "480")
