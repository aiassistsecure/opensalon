from django.test import TestCase

from saloncore.add_staff_level import add_staff_level, validate_add_staff_level
from saloncore.models import Salon, StaffLevel


class AddStaffLevelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def test_creates_with_all_fields(self):
        lvl = add_staff_level(self.salon, "  Level 6  ", sort_order=6, active=False)
        self.assertEqual(StaffLevel.objects.count(), 1)
        self.assertEqual(
            (lvl.salon, lvl.name, lvl.sort_order, lvl.active),
            (self.salon, "Level 6", 6, False))

    def test_defaults_sort_order_zero_active_true(self):
        lvl = add_staff_level(self.salon, "Junior")
        self.assertEqual((lvl.sort_order, lvl.active), (0, True))

    def test_scoped_to_given_salon_and_duplicates_allowed(self):
        a = add_staff_level(self.salon, "Senior")
        b = add_staff_level(self.other, "Senior")
        c = add_staff_level(self.salon, "Senior")
        self.assertEqual((a.salon, b.salon), (self.salon, self.other))
        self.assertEqual(StaffLevel.objects.count(), 3)
        self.assertNotEqual(a.pk, c.pk)

    def test_string_sort_order_accepted(self):
        lvl = add_staff_level(self.salon, "Level 2", sort_order="2")
        self.assertEqual(lvl.sort_order, 2)

    def test_blank_or_overlong_name_refused(self):
        for bad in ("", "   ", None, 123, "x" * 121):
            with self.assertRaises(ValueError):
                add_staff_level(self.salon, bad)
        self.assertEqual(StaffLevel.objects.count(), 0)

    def test_bad_sort_order_and_active_refused(self):
        for kwargs in ({"sort_order": -1}, {"sort_order": "abc"},
                       {"sort_order": 1.5}, {"sort_order": True},
                       {"sort_order": None}, {"active": "yes"},
                       {"active": 1}):
            with self.assertRaises(ValueError):
                add_staff_level(self.salon, "Level 1", **kwargs)
        self.assertEqual(StaffLevel.objects.count(), 0)

    def test_unsaved_salon_refused(self):
        with self.assertRaises(ValueError):
            add_staff_level(Salon(name="Unsaved"), "Level 1")
        self.assertEqual(StaffLevel.objects.count(), 0)

    def test_validate_writes_nothing(self):
        cleaned = validate_add_staff_level(
            self.salon, "  Level 3  ", sort_order="3", active=False)
        self.assertEqual(StaffLevel.objects.count(), 0)
        self.assertEqual(
            (cleaned["salon"], cleaned["name"],
             cleaned["sort_order"], cleaned["active"]),
            (self.salon, "Level 3", 3, False))

    def test_validate_rejects_invalid_writing_nothing(self):
        for kwargs in ({"name": " "}, {"name": "L", "sort_order": -2}):
            with self.assertRaises(ValueError):
                validate_add_staff_level(self.salon, **kwargs)
        self.assertEqual(StaffLevel.objects.count(), 0)
