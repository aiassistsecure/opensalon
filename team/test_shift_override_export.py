"""Shift override export: stored ShiftOverride rows verbatim."""
import csv
import datetime
import io

from django.test import TestCase

from saloncore.models import Salon
from team.models import ShiftOverride, StaffMember
from team.shift_override_export import (
    EXPORT_FIELDNAMES,
    SHIFT_OVERRIDE_EXPORT_FIELDNAMES,
    export_shift_overrides,
    export_shift_overrides_csv,
    shift_overrides_csv,
)

PLACED_DATE = datetime.date(2026, 10, 31)
OFF_DATE = datetime.date(2026, 11, 7)


class ShiftOverrideExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Override Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other", timezone="UTC")
        # PIN and email are set so the hygiene test is meaningful.
        self.dana = StaffMember.objects.create(
            salon=self.salon, display_name="Dana",
            pin="1234", email="dana@example.com")
        self.other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Dana")

    def _placed(self, staff=None, day=PLACED_DATE):
        return ShiftOverride.objects.create(
            staff_member=staff or self.dana, date=day,
            start_time=datetime.time(10, 0),
            end_time=datetime.time(14, 0))

    def _off(self, staff=None, day=OFF_DATE):
        return ShiftOverride.objects.create(
            staff_member=staff or self.dana, date=day, is_off=True)

    def test_header_and_dict_keys(self):
        self._placed()
        text = export_shift_overrides_csv(self.salon)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], SHIFT_OVERRIDE_EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, SHIFT_OVERRIDE_EXPORT_FIELDNAMES)
        records = export_shift_overrides(self.salon)
        self.assertEqual(len(records), 1)
        self.assertEqual(list(records[0].keys()),
                         SHIFT_OVERRIDE_EXPORT_FIELDNAMES)
        self.assertIs(shift_overrides_csv, export_shift_overrides_csv)

    def test_placed_shift_shape_verbatim(self):
        placed = self._placed()
        records = export_shift_overrides(self.salon)
        self.assertEqual(records, [{
            "id": placed.pk, "salon_id": self.salon.pk,
            "staff_member_id": self.dana.pk, "staff_name": "Dana",
            "date": "2026-10-31", "is_off": False,
            "start_time": "10:00:00", "end_time": "14:00:00"}])
        parsed = list(csv.DictReader(io.StringIO(
            export_shift_overrides_csv(self.salon))))
        self.assertEqual(parsed[0]["is_off"], "False")
        self.assertEqual(parsed[0]["start_time"], "10:00:00")
        self.assertEqual(parsed[0]["end_time"], "14:00:00")

    def test_full_day_off_shape_verbatim(self):
        off = self._off()
        records = export_shift_overrides(self.salon)
        self.assertEqual(records, [{
            "id": off.pk, "salon_id": self.salon.pk,
            "staff_member_id": self.dana.pk, "staff_name": "Dana",
            "date": "2026-11-07", "is_off": True,
            "start_time": None, "end_time": None}])
        parsed = list(csv.DictReader(io.StringIO(
            export_shift_overrides_csv(self.salon))))
        self.assertEqual(parsed[0]["is_off"], "True")
        self.assertEqual(parsed[0]["start_time"], "")
        self.assertEqual(parsed[0]["end_time"], "")

    def test_both_shapes_in_model_date_order(self):
        off = self._off()
        placed = self._placed()
        records = export_shift_overrides(self.salon)
        self.assertEqual([r["id"] for r in records],
                         [placed.pk, off.pk])

    def test_salon_scoping_and_empty(self):
        self._placed()
        self._placed(staff=self.other_staff)
        self.assertEqual(len(export_shift_overrides(self.salon)), 1)
        self.assertEqual(len(export_shift_overrides(self.other_salon)), 1)
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_shift_overrides(empty), [])
        self.assertEqual(
            export_shift_overrides_csv(empty),
            ",".join(SHIFT_OVERRIDE_EXPORT_FIELDNAMES) + "\n")

    def test_no_pin_or_email_anywhere(self):
        self._placed()
        self.assertNotIn("pin", SHIFT_OVERRIDE_EXPORT_FIELDNAMES)
        self.assertNotIn("email", SHIFT_OVERRIDE_EXPORT_FIELDNAMES)
        text = export_shift_overrides_csv(self.salon)
        self.assertNotIn("1234", text)
        self.assertNotIn("dana@example.com", text)

    def test_default_none_is_salon_wide_unchanged(self):
        self._placed()
        self._off()
        expected_records = export_shift_overrides(self.salon)
        expected_csv = export_shift_overrides_csv(self.salon)
        self.assertEqual(
            export_shift_overrides(self.salon, staff_member=None),
            expected_records)
        self.assertEqual(
            export_shift_overrides_csv(
                self.salon, staff_member=None),
            expected_csv)

    def test_filtered_by_staff_member(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        placed = self._placed()
        self._placed(staff=eve, day=datetime.date(2026, 11, 1))
        off = self._off()
        records = export_shift_overrides(
            self.salon, staff_member=self.dana)
        self.assertEqual([r["id"] for r in records],
                         [placed.pk, off.pk])
        self.assertTrue(
            all(r["staff_name"] == "Dana" for r in records))
        parsed = list(csv.DictReader(io.StringIO(
            export_shift_overrides_csv(
                self.salon, staff_member=self.dana))))
        self.assertEqual([int(r["id"]) for r in parsed],
                         [placed.pk, off.pk])

    def test_filtered_staff_member_with_no_overrides(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        self._placed()
        self.assertEqual(
            export_shift_overrides(self.salon, staff_member=eve),
            [])
        self.assertEqual(
            export_shift_overrides_csv(
                self.salon, staff_member=eve),
            ",".join(SHIFT_OVERRIDE_EXPORT_FIELDNAMES) + "\n")

    def test_filtered_staff_member_from_other_salon_is_empty(self):
        self._placed()
        self._placed(staff=self.other_staff)
        self.assertEqual(
            export_shift_overrides(
                self.salon, staff_member=self.other_staff),
            [])
        self.assertEqual(
            export_shift_overrides_csv(
                self.salon, staff_member=self.other_staff),
            ",".join(SHIFT_OVERRIDE_EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(
            len(export_shift_overrides(
                self.other_salon, staff_member=self.other_staff)),
            1)

    def test_window_defaults_none_is_unchanged(self):
        self._placed()
        self._off()
        self.assertEqual(
            export_shift_overrides(
                self.salon, start_date=None, end_date=None),
            export_shift_overrides(self.salon))
        self.assertEqual(
            export_shift_overrides_csv(
                self.salon, start_date=None, end_date=None),
            export_shift_overrides_csv(self.salon))

    def test_window_inclusive_on_override_date(self):
        placed = self._placed()
        off = self._off()
        records = export_shift_overrides(
            self.salon, start_date=PLACED_DATE, end_date=PLACED_DATE)
        self.assertEqual([r["id"] for r in records], [placed.pk])
        records = export_shift_overrides(
            self.salon, start_date=PLACED_DATE, end_date=OFF_DATE)
        self.assertEqual([r["id"] for r in records],
                         [placed.pk, off.pk])
        parsed = list(csv.DictReader(io.StringIO(
            export_shift_overrides_csv(
                self.salon, start_date=OFF_DATE, end_date=OFF_DATE))))
        self.assertEqual([int(r["id"]) for r in parsed], [off.pk])

    def test_window_start_only_and_end_only(self):
        placed = self._placed()
        off = self._off()
        self.assertEqual(
            [r["id"] for r in export_shift_overrides(
                self.salon, start_date=OFF_DATE)],
            [off.pk])
        self.assertEqual(
            [r["id"] for r in export_shift_overrides(
                self.salon, end_date=PLACED_DATE)],
            [placed.pk])

    def test_window_reversed_is_empty(self):
        self._placed()
        self._off()
        self.assertEqual(
            export_shift_overrides(
                self.salon, start_date=OFF_DATE, end_date=PLACED_DATE),
            [])
        self.assertEqual(
            export_shift_overrides_csv(
                self.salon, start_date=OFF_DATE, end_date=PLACED_DATE),
            ",".join(SHIFT_OVERRIDE_EXPORT_FIELDNAMES) + "\n")

    def test_window_aliases_and_datetime_bounds(self):
        self._placed()
        self._off()
        expected = export_shift_overrides(
            self.salon, start_date=PLACED_DATE, end_date=PLACED_DATE)
        self.assertEqual(
            export_shift_overrides(
                self.salon, start=PLACED_DATE, end=PLACED_DATE),
            expected)
        self.assertEqual(
            export_shift_overrides(
                self.salon, date_from=PLACED_DATE, date_to=PLACED_DATE),
            expected)
        self.assertEqual(
            export_shift_overrides(
                self.salon,
                start_date=datetime.datetime(2026, 10, 31, 23, 0),
                end_date=datetime.datetime(2026, 10, 31, 1, 0)),
            expected)

    def test_window_composes_with_staff_member(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        placed = self._placed()
        self._placed(staff=eve, day=PLACED_DATE)
        self._off()
        records = export_shift_overrides(
            self.salon, staff_member=self.dana,
            start_date=PLACED_DATE, end_date=PLACED_DATE)
        self.assertEqual([r["id"] for r in records], [placed.pk])

    def test_read_only(self):
        self._placed()
        self._off()
        before = ShiftOverride.objects.count()
        export_shift_overrides(self.salon)
        export_shift_overrides_csv(self.salon)
        self.assertEqual(ShiftOverride.objects.count(), before)
