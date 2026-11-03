from django.test import TestCase

from saloncore.add_service import add_service
from saloncore.models import Salon, Service, ServiceCategory
from saloncore.update_service import update_service, validate_update_service


class UpdateServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.cuts = ServiceCategory.objects.create(
            salon=self.salon, name="Cuts")
        self.other_category = ServiceCategory.objects.create(
            salon=self.other, name="Color")
        self.service = add_service(
            self.salon, "Full Color", 60, category=self.category,
            description="All-over", processing_minutes=30,
            finishing_minutes=15)
        self.foreign = add_service(
            self.other, "Cut", 45, category=self.other_category)

    def stored(self):
        return Service.objects.get(pk=self.service.pk)

    def test_updates_all_fields_and_returns_service(self):
        s = update_service(
            self.salon, self.service, name="  Balayage  ",
            description="New desc", category=self.cuts,
            service_minutes=90, processing_minutes=20,
            finishing_minutes=10, active=False)
        self.assertIs(s, self.service)
        stored = self.stored()
        self.assertEqual(
            (stored.category, stored.name, stored.description,
             stored.service_minutes, stored.processing_minutes,
             stored.finishing_minutes, stored.active, stored.prices.count()),
            (self.cuts, "Balayage", "New desc", 90, 20, 10, False, 0))

    def test_omitted_fields_unchanged_none_sentinel(self):
        update_service(self.salon, self.service, service_minutes=75)
        stored = self.stored()
        self.assertEqual(
            (stored.category, stored.name, stored.description,
             stored.service_minutes, stored.processing_minutes,
             stored.finishing_minutes, stored.active),
            (self.category, "Full Color", "All-over", 75, 30, 15, True))

    def test_explicit_blank_description_clears_and_string_minutes(self):
        update_service(self.salon, self.service, description="",
                       processing_minutes="5")
        stored = self.stored()
        self.assertEqual((stored.description, stored.processing_minutes),
                         ("", 5))

    def test_category_by_id_and_by_name_inside_salon(self):
        update_service(self.salon, self.service, category=self.cuts.pk)
        self.assertEqual(self.stored().category, self.cuts)
        update_service(self.salon, self.service, category_name=" Color ")
        self.assertEqual(self.stored().category, self.category)

    def test_category_unknown_ambiguous_both_cross_salon_refused(self):
        ServiceCategory.objects.create(salon=self.salon, name="Color")
        for kwargs in ({"category_name": "Missing"},
                       {"category_name": "Color"},
                       {"category": 999999},
                       {"category": self.cuts, "category_name": "Cuts"},
                       {"category": self.other_category},
                       {"category": self.other_category.pk}):
            with self.assertRaises(ValueError):
                update_service(self.salon, self.service, **kwargs)
        self.assertEqual(self.stored().category, self.category)

    def test_no_field_given_refused(self):
        with self.assertRaises(ValueError):
            update_service(self.salon, self.service)
        with self.assertRaises(ValueError):
            validate_update_service(self.salon, self.service)

    def test_bad_values_refused_and_nothing_written(self):
        cases = (
            {"name": "   "}, {"name": "x" * 201}, {"name": 123},
            {"description": 123}, {"service_minutes": 0},
            {"service_minutes": "abc"}, {"service_minutes": 45.5},
            {"processing_minutes": -1}, {"finishing_minutes": True},
            {"active": "yes"})
        for kwargs in cases:
            with self.assertRaises(ValueError):
                update_service(self.salon, self.service, **kwargs)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.service_minutes, stored.active),
            ("Full Color", 60, True))

    def test_unsaved_or_cross_salon_salon_and_service_refused(self):
        for call in (
                lambda: update_service(
                    Salon(name="Unsaved"), self.service, name="X"),
                lambda: update_service(
                    self.salon, Service(name="Unsaved"), name="X"),
                lambda: update_service(
                    self.salon, self.foreign, name="X"),
                lambda: update_service(
                    self.other, self.service, name="X")):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(self.stored().name, "Full Color")

    def test_validate_returns_only_given_fields_and_writes_nothing(self):
        cleaned = validate_update_service(
            self.salon, self.service, name="  New  ", active=False,
            category_name="Cuts")
        self.assertEqual(
            cleaned, {"category": self.cuts, "name": "New", "active": False})
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.category, stored.active),
            ("Full Color", self.category, True))

    def test_validate_same_errors_writes_nothing(self):
        for kwargs in ({"name": " "}, {"service_minutes": 0},
                       {"category_name": "Missing"}, {"active": 1}):
            with self.assertRaises(ValueError):
                validate_update_service(self.salon, self.service, **kwargs)
        self.assertEqual(self.stored().name, "Full Color")
