from django.test import TestCase

from saloncore.add_service_category import add_service_category
from saloncore.models import Salon, ServiceCategory
from saloncore.update_service_category import (
    update_service_category,
    validate_update_service_category,
)


class UpdateServiceCategoryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.category = add_service_category(
            self.salon, "Haircuts", sort_order=6, active=True)
        self.foreign = add_service_category(self.other, "Color")

    def stored(self):
        return ServiceCategory.objects.get(pk=self.category.pk)

    def test_updates_all_fields_and_returns_category(self):
        cat = update_service_category(
            self.salon, self.category, name="  Hair  ",
            sort_order=8, active=False)
        self.assertIs(cat, self.category)
        stored = self.stored()
        self.assertEqual(
            (stored.salon, stored.name, stored.sort_order, stored.active),
            (self.salon, "Hair", 8, False))

    def test_omitted_fields_unchanged_none_sentinel(self):
        update_service_category(self.salon, self.category, sort_order=3)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Haircuts", 3, True))

    def test_string_sort_order_accepted(self):
        update_service_category(self.salon, self.category, sort_order="2")
        self.assertEqual(self.stored().sort_order, 2)

    def test_duplicate_name_allowed_no_uniqueness(self):
        add_service_category(self.salon, "Color")
        update_service_category(self.salon, self.category, name="Color")
        self.assertEqual(self.stored().name, "Color")
        self.assertEqual(
            ServiceCategory.objects.filter(
                salon=self.salon, name="Color").count(), 2)

    def test_no_field_given_refused(self):
        with self.assertRaises(ValueError):
            update_service_category(self.salon, self.category)
        with self.assertRaises(ValueError):
            validate_update_service_category(self.salon, self.category)
        self.assertEqual(self.stored().name, "Haircuts")

    def test_bad_values_refused_and_nothing_written(self):
        cases = (
            {"name": "   "}, {"name": "x" * 121}, {"name": 123},
            {"sort_order": -1}, {"sort_order": "abc"},
            {"sort_order": 1.5}, {"sort_order": True},
            {"active": "yes"}, {"active": 1})
        for kwargs in cases:
            with self.assertRaises(ValueError):
                update_service_category(self.salon, self.category, **kwargs)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Haircuts", 6, True))

    def test_unsaved_or_cross_salon_salon_and_category_refused(self):
        for call in (
                lambda: update_service_category(
                    Salon(name="Unsaved"), self.category, name="X"),
                lambda: update_service_category(
                    self.salon, ServiceCategory(name="Unsaved"), name="X"),
                lambda: update_service_category(
                    self.salon, self.foreign, name="X"),
                lambda: update_service_category(
                    self.other, self.category, name="X")):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self.stored().name, "Haircuts")

    def test_validate_returns_only_given_fields_and_writes_nothing(self):
        cleaned = validate_update_service_category(
            self.salon, self.category, name="  New  ", active=False)
        self.assertEqual(cleaned, {"name": "New", "active": False})
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Haircuts", 6, True))

    def test_validate_same_errors_writes_nothing(self):
        for kwargs in ({"name": " "}, {"sort_order": -2},
                       {"active": 1}):
            with self.assertRaises(ValueError):
                validate_update_service_category(
                    self.salon, self.category, **kwargs)
        self.assertEqual(self.stored().name, "Haircuts")
