import csv
import datetime
import io

from django.test import TestCase

from saloncore.models import Salon
from team.models import RosterPattern, StaffMember
from team.roster_week_export import (
    EXPORT_FIELDNAMES,
    ROSTER_WEEK_EXPORT_FIELDNAMES,
    export_roster_week,
    export_roster_week_csv,
    roster_week_csv,
)

MONDAY = datetime.date(2026, 11, 2)  # a Monday
SUNDAY = datetime.date(2026, 11, 8)


class RosterWeekExportTests(TestCase):
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
        text = export_roster_week_csv(self.salon, MONDAY)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], ROSTER_WEEK_EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, ROSTER_WEEK_EXPORT_FIELDNAMES)
        for record in export_roster_week(self.salon, MONDAY):
            self.assertEqual(
                list(record.keys()), ROSTER_WEEK_EXPORT_FIELDNAMES)
        self.assertIs(roster_week_csv, export_roster_week_csv)

    def test_row_fields_from_service_structure(self):
        self._pattern(weekday=0, start=(9, 0), end=(17, 0))
        records = export_roster_week(self.salon, MONDAY)
        staff_rows = [r for r in records
                      if r["staff_member_id"] == self.staff.pk]
        monday = [r for r in staff_rows if r["date"] == "2026-11-02"]
        self.assertEqual(monday, [{
            "salon_id": self.salon.pk,
            "week_start": "2026-11-02",
            "week_end": "2026-11-08",
            "staff_member_id": self.staff.pk,
            "staff_name": "Stylist One",
            "online_bookable": True,
            "date": "2026-11-02",
            "interval_start": "2026-11-02T09:00:00+00:00",
            "interval_end": "2026-11-02T17:00:00+00:00",
            "interval_minutes": 480,
            "day_total_minutes": 480,
            "is_working": True,
        }])

    def test_off_day_present_with_empty_interval_fields(self):
        self._pattern(weekday=0)
        records = export_roster_week(self.salon, MONDAY)
        staff_rows = [r for r in records
                      if r["staff_member_id"] == self.staff.pk]
        # Seven days are all present: one interval row for Monday
        # plus one empty row for each of the six off days.
        self.assertEqual(len(staff_rows), 7)
        self.assertEqual(
            [r["date"] for r in staff_rows],
            [(MONDAY + datetime.timedelta(days=i)).isoformat()
             for i in range(7)])
        tuesday = staff_rows[1]
        self.assertIsNone(tuesday["interval_start"])
        self.assertIsNone(tuesday["interval_end"])
        self.assertIsNone(tuesday["interval_minutes"])
        self.assertEqual(tuesday["day_total_minutes"], 0)
        self.assertFalse(tuesday["is_working"])

    def test_split_shift_flattens_to_one_row_per_interval(self):
        self._pattern(weekday=2, start=(9, 0), end=(12, 0))
        self._pattern(weekday=2, start=(13, 0), end=(17, 0))
        records = export_roster_week(self.salon, MONDAY)
        wednesday = [r for r in records
                     if r["staff_member_id"] == self.staff.pk
                     and r["date"] == "2026-11-04"]
        self.assertEqual(
            [(r["interval_start"], r["interval_end"],
              r["interval_minutes"]) for r in wednesday],
            [("2026-11-04T09:00:00+00:00",
              "2026-11-04T12:00:00+00:00", 180),
             ("2026-11-04T13:00:00+00:00",
              "2026-11-04T17:00:00+00:00", 240)])
        self.assertTrue(all(
            r["day_total_minutes"] == 420 for r in wednesday))

    def test_online_bookable_flag_separate_and_never_removes_intervals(self):
        self._pattern(staff=self.offline, weekday=0)
        records = export_roster_week(self.salon, MONDAY)
        monday = [r for r in records
                  if r["staff_member_id"] == self.offline.pk
                  and r["date"] == "2026-11-02"]
        self.assertEqual(len(monday), 1)
        self.assertFalse(monday[0]["online_bookable"])
        self.assertEqual(monday[0]["interval_minutes"], 480)
        self.assertTrue(monday[0]["is_working"])

    def test_ordering_is_service_order_staff_then_day(self):
        self._pattern()
        self._pattern(staff=self.offline)
        records = export_roster_week(self.salon, MONDAY)
        # "Offline Two" sorts before "Stylist One" (display name);
        # each member's rows run Monday through Sunday.
        self.assertEqual(
            [r["staff_name"] for r in records],
            ["Offline Two"] * 7 + ["Stylist One"] * 7)
        self.assertEqual(SUNDAY.isoformat(), records[6]["date"])

    def test_non_monday_input_snaps_to_monday_via_service(self):
        wednesday = MONDAY + datetime.timedelta(days=2)
        records = export_roster_week(self.salon, wednesday)
        self.assertTrue(records)
        self.assertTrue(all(
            r["week_start"] == "2026-11-02" for r in records))
        self.assertTrue(all(
            r["week_end"] == "2026-11-08" for r in records))

    def test_csv_agrees_with_dict_export(self):
        self._pattern(weekday=0)
        self._pattern(weekday=2, start=(13, 0), end=(17, 0))
        records = export_roster_week(self.salon, MONDAY)
        parsed = list(csv.DictReader(io.StringIO(
            export_roster_week_csv(self.salon, MONDAY))))
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
        # Empty interval fields render as empty CSV cells.
        self.assertEqual(parsed[0]["interval_minutes"], "")
        self.assertTrue(export_roster_week_csv(
            self.salon, MONDAY).endswith("\n"))

    def test_empty_salon_is_header_only_and_missing_args_raise(self):
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_roster_week(empty, MONDAY), [])
        self.assertEqual(
            export_roster_week_csv(empty, MONDAY),
            ",".join(ROSTER_WEEK_EXPORT_FIELDNAMES) + "\n")
        with self.assertRaises(ValueError):
            export_roster_week(None, MONDAY)
        with self.assertRaises(ValueError):
            export_roster_week(self.salon, None)

    def test_read_only(self):
        self._pattern()
        before = (StaffMember.objects.count(),
                  RosterPattern.objects.count())
        export_roster_week(self.salon, MONDAY)
        export_roster_week_csv(self.salon, MONDAY)
        self.assertEqual(
            (StaffMember.objects.count(),
             RosterPattern.objects.count()), before)
