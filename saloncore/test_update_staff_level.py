from django.test import TestCase

from saloncore.add_staff_level import add_staff_level
from saloncore.models import Salon, StaffLevel
from saloncore.update_staff_level import (
    update_staff_level,
    validate_update_staff_level,
)


class UpdateStaffLevelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.level = add_staff_level(
            self.salon, "Level 6", sort_order=6, active=True)
        self.foreign = add_staff_level(self.other, "Level 1")

    def stored(self):
        return StaffLevel.objects.get(pk=self.level.pk)

    def test_updates_all_fields_and_returns_level(self):
        lvl = update_staff_level(
            self.salon, self.level, name="  Level 8  ",
            sort_order=8, active=False)
        self.assertIs(lvl, self.level)
        stored = self.stored()
        self.assertEqual(
            (stored.salon, stored.name, stored.sort_order, stored.active),
            (self.salon, "Level 8", 8, False))

    def test_omitted_fields_unchanged_none_sentinel(self):
        update_staff_level(self.salon, self.level, sort_order=3)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Level 6", 3, True))

    def test_string_sort_order_accepted(self):
        update_staff_level(self.salon, self.level, sort_order="2")
        self.assertEqual(self.stored().sort_order, 2)

    def test_duplicate_name_allowed_no_uniqueness(self):
        add_staff_level(self.salon, "Senior")
        update_staff_level(self.salon, self.level, name="Senior")
        self.assertEqual(self.stored().name, "Senior")
        self.assertEqual(
            StaffLevel.objects.filter(
                salon=self.salon, name="Senior").count(), 2)

    def test_no_field_given_refused(self):
        with self.assertRaises(ValueError):
            update_staff_level(self.salon, self.level)
        with self.assertRaises(ValueError):
            validate_update_staff_level(self.salon, self.level)
        self.assertEqual(self.stored().name, "Level 6")

    def test_bad_values_refused_and_nothing_written(self):
        cases = (
            {"name": "   "}, {"name": "x" * 121}, {"name": 123},
            {"sort_order": -1}, {"sort_order": "abc"},
            {"sort_order": 1.5}, {"sort_order": True},
            {"active": "yes"}, {"active": 1})
        for kwargs in cases:
            with self.assertRaises(ValueError):
                update_staff_level(self.salon, self.level, **kwargs)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Level 6", 6, True))

    def test_unsaved_or_cross_salon_salon_and_level_refused(self):
        for call in (
                lambda: update_staff_level(
                    Salon(name="Unsaved"), self.level, name="X"),
                lambda: update_staff_level(
                    self.salon, StaffLevel(name="Unsaved"), name="X"),
                lambda: update_staff_level(
                    self.salon, self.foreign, name="X"),
                lambda: update_staff_level(
                    self.other, self.level, name="X")):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self.stored().name, "Level 6")

    def test_validate_returns_only_given_fields_and_writes_nothing(self):
        cleaned = validate_update_staff_level(
            self.salon, self.level, name="  New  ", active=False)
        self.assertEqual(cleaned, {"name": "New", "active": False})
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Level 6", 6, True))

    def test_validate_same_errors_writes_nothing(self):
        for kwargs in ({"name": " "}, {"sort_order": -2},
                       {"active": 1}):
            with self.assertRaises(ValueError):
                validate_update_staff_level(self.salon, self.level, **kwargs)
        self.assertEqual(self.stored().name, "Level 6")
