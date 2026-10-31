import csv
import datetime
import io

from django.test import TestCase

from saloncore.models import Salon
from team.models import RosterPattern, StaffMember
from team.roster_export import (
    EXPORT_FIELDNAMES,
    ROSTER_EXPORT_FIELDNAMES,
    export_roster,
    export_roster_patterns,
    export_roster_patterns_csv,
    roster_patterns_csv,
)


class RosterExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other", timezone="UTC")
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
        text = export_roster_patterns_csv(self.salon)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], ROSTER_EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, ROSTER_EXPORT_FIELDNAMES)
        records = export_roster_patterns(self.salon)
        self.assertEqual(len(records), 1)
        for record in records:
            self.assertEqual(
                list(record.keys()), ROSTER_EXPORT_FIELDNAMES)
        self.assertIs(roster_patterns_csv, export_roster_patterns_csv)
        self.assertIs(export_roster, export_roster_patterns)
        self.assertEqual(
            export_roster_patterns_csv(self.salon), text)

    def test_row_fields_exactly_as_model_defines_them(self):
        pattern = self._pattern(weekday=2, start=(9, 30), end=(13, 15))
        self._pattern(staff=self.offline, weekday=4)
        records = {
            r["staff_member_id"]: r
            for r in export_roster_patterns(self.salon)}
        self.assertEqual(records[self.staff.pk], {
            "id": pattern.pk,
            "salon_id": self.salon.pk,
            "staff_member_id": self.staff.pk,
            "staff_name": "Stylist One",
            "staff_active": True,
            "online_bookable": True,
            "weekday": 2,
            "start_time": "09:30:00",
            "end_time": "13:15:00",
            "active": True,
        })
        # online_bookable is the staff member's toggle, verbatim,
        # and never removes or alters the pattern row.
        offline_row = records[self.offline.pk]
        self.assertFalse(offline_row["online_bookable"])
        self.assertTrue(offline_row["active"])
        # CSV agrees with the dict export on the same arguments.
        parsed = list(csv.DictReader(io.StringIO(
            export_roster_patterns_csv(self.salon))))
        self.assertEqual(len(parsed), len(records))
        parsed_by_staff = {
            int(r["staff_member_id"]): r for r in parsed}
        self.assertEqual(
            parsed_by_staff[self.staff.pk]["weekday"],
            str(records[self.staff.pk]["weekday"]))

    def test_salon_scoping(self):
        self._pattern()
        other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Stylist")
        self._pattern(staff=other_staff)
        records = export_roster_patterns(self.salon)
        self.assertEqual(
            [r["staff_member_id"] for r in records], [self.staff.pk])
        self.assertTrue(all(
            r["salon_id"] == self.salon.pk for r in records))
        other_records = export_roster_patterns(self.other_salon)
        self.assertEqual(
            [r["staff_member_id"] for r in other_records],
            [other_staff.pk])
        self.assertEqual(export_roster_patterns(None), [])
        self.assertEqual(
            export_roster_patterns_csv(None),
            ",".join(ROSTER_EXPORT_FIELDNAMES) + "\n")

    def test_inactive_patterns_excluded_by_default_included_on_request(self):
        active = self._pattern(weekday=0)
        inactive = self._pattern(weekday=1, active=False)
        default = export_roster_patterns(self.salon)
        self.assertEqual([r["id"] for r in default], [active.pk])
        complete = export_roster_patterns(
            self.salon, include_inactive=True)
        self.assertEqual(
            [r["id"] for r in complete], [active.pk, inactive.pk])
        self.assertEqual(
            [r["active"] for r in complete], [True, False])
        parsed = list(csv.DictReader(io.StringIO(
            export_roster_patterns_csv(
                self.salon, include_inactive=True))))
        self.assertEqual(
            [r["active"] for r in parsed], ["True", "False"])

    def test_inactive_staff_patterns_still_export_with_staff_active(self):
        inactive_staff = StaffMember.objects.create(
            salon=self.salon, display_name="Aardvark Inactive",
            active=False)
        self._pattern(staff=inactive_staff)
        records = export_roster_patterns(self.salon)
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]["staff_active"])
        self.assertEqual(records[0]["staff_name"], "Aardvark Inactive")

    def test_ordering_by_staff_name_weekday_start_then_id(self):
        # Created out of order on purpose.
        late = self._pattern(weekday=0, start=(13, 0), end=(17, 0))
        early = self._pattern(weekday=0, start=(9, 0), end=(12, 0))
        tuesday = self._pattern(weekday=1, start=(9, 0), end=(17, 0))
        offline_mon = self._pattern(
            staff=self.offline, weekday=0, start=(8, 0), end=(10, 0))
        records = export_roster_patterns(self.salon)
        # "Offline Two" sorts before "Stylist One" by display name;
        # within a staff member: weekday, then start_time.
        self.assertEqual(
            [r["id"] for r in records],
            [offline_mon.pk, early.pk, late.pk, tuesday.pk])

    def test_empty_roster_is_header_only(self):
        self.assertEqual(export_roster_patterns(self.salon), [])
        self.assertEqual(
            export_roster_patterns_csv(self.salon),
            ",".join(ROSTER_EXPORT_FIELDNAMES) + "\n")

    def test_read_only(self):
        self._pattern()
        before_patterns = RosterPattern.objects.count()
        before_staff = StaffMember.objects.count()
        export_roster_patterns(self.salon, include_inactive=True)
        export_roster_patterns_csv(self.salon, include_inactive=True)
        self.assertEqual(RosterPattern.objects.count(), before_patterns)
        self.assertEqual(StaffMember.objects.count(), before_staff)
