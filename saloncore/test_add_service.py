from django.test import TestCase

from saloncore.add_service import add_service, validate_add_service
from saloncore.models import Salon, Service, ServiceCategory


class AddServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.other_category = ServiceCategory.objects.create(
            salon=self.other, name="Color")

    def test_creates_service_with_all_fields(self):
        s = add_service(
            self.salon, "  Full Color  ", 60, category=self.category,
            description="All-over colour", processing_minutes=30,
            finishing_minutes=15)
        self.assertEqual(Service.objects.count(), 1)
        self.assertEqual(
            (s.category, s.name, s.description, s.service_minutes,
             s.processing_minutes, s.finishing_minutes, s.active,
             s.external_id, s.total_minutes),
            (self.category, "Full Color", "All-over colour", 60,
             30, 15, True, "", 105))
        self.assertEqual(s.prices.count(), 0)

    def test_defaults_description_blank_segments_zero_active(self):
        s = add_service(self.salon, "Cut", 45, category=self.category)
        self.assertEqual(
            (s.description, s.processing_minutes, s.finishing_minutes,
             s.active), ("", 0, 0, True))

    def test_category_by_id(self):
        s = add_service(self.salon, "Cut", 45, category=self.category.pk)
        self.assertEqual(s.category, self.category)

    def test_category_by_name_resolved_inside_salon(self):
        s = add_service(self.salon, "Cut", 45, category_name=" Color ")
        self.assertEqual(s.category, self.category)

    def test_category_name_unknown_or_ambiguous_refused(self):
        ServiceCategory.objects.create(salon=self.salon, name="Color")
        for kwargs in ({"category_name": "Missing"},
                       {"category_name": "Color"}):
            with self.assertRaises(ValueError):
                add_service(self.salon, "Cut", 45, **kwargs)
        self.assertEqual(Service.objects.count(), 0)

    def test_category_missing_both_or_unknown_id_refused(self):
        for kwargs in ({}, {"category": self.category,
                            "category_name": "Color"},
                       {"category": 999999}):
            with self.assertRaises(ValueError):
                add_service(self.salon, "Cut", 45, **kwargs)
        self.assertEqual(Service.objects.count(), 0)

    def test_cross_salon_category_refused_by_instance_id_and_name(self):
        # Same name exists in both salons; name resolution must stay
        # inside the salon, instance/id must match the salon.
        s = add_service(self.other, "Cut", 45, category_name="Color")
        self.assertEqual(s.category, self.other_category)
        for kwargs in ({"category": self.other_category},
                       {"category": self.other_category.pk}):
            with self.assertRaises(ValueError):
                add_service(self.salon, "Cut", 45, **kwargs)
        self.assertEqual(Service.objects.count(), 1)

    def test_blank_or_overlong_name_refused(self):
        for bad in ("", "   ", None, 123, "x" * 201):
            with self.assertRaises(ValueError):
                add_service(self.salon, bad, 45, category=self.category)
        self.assertEqual(Service.objects.count(), 0)

    def test_bad_minutes_refused(self):
        cases = (
            {"service_minutes": None}, {"service_minutes": 0},
            {"service_minutes": -5}, {"service_minutes": "abc"},
            {"service_minutes": 45.5}, {"service_minutes": True},
            {"service_minutes": 45, "processing_minutes": -1},
            {"service_minutes": 45, "finishing_minutes": "x"})
        for kwargs in cases:
            with self.assertRaises(ValueError):
                add_service(
                    self.salon, "Cut", category=self.category, **kwargs)
        self.assertEqual(Service.objects.count(), 0)

    def test_string_minutes_accepted(self):
        s = add_service(self.salon, "Cut", "45", category=self.category,
                        processing_minutes="10")
        self.assertEqual((s.service_minutes, s.processing_minutes), (45, 10))

    def test_unsaved_salon_or_category_and_non_bool_active_refused(self):
        for call in (
                lambda: add_service(
                    Salon(name="Unsaved"), "Cut", 45, category=self.category),
                lambda: add_service(
                    self.salon, "Cut", 45,
                    category=ServiceCategory(salon=self.salon, name="New")),
                lambda: add_service(
                    self.salon, "Cut", 45, category=self.category,
                    active="yes"),
                lambda: add_service(
                    self.salon, "Cut", 45, category=self.category,
                    description=123)):
            with self.assertRaises(ValueError):
                call()
        self.assertEqual(Service.objects.count(), 0)

    def test_validate_add_service_writes_nothing(self):
        cleaned = validate_add_service(
            self.salon, "  Cut  ", "45", category_name="Color",
            processing_minutes=5)
        self.assertEqual(Service.objects.count(), 0)
        self.assertEqual(
            (cleaned["category"], cleaned["name"],
             cleaned["service_minutes"], cleaned["processing_minutes"]),
            (self.category, "Cut", 45, 5))

    def test_validate_add_service_same_errors_writes_nothing(self):
        for kwargs in ({"name": " ", "service_minutes": 45,
                        "category": self.category},
                       {"name": "Cut", "service_minutes": 0,
                        "category": self.category},
                       {"name": "Cut", "service_minutes": 45,
                        "category_name": "Missing"},
                       {"name": "Cut", "service_minutes": 45,
                        "category": self.other_category}):
            with self.assertRaises(ValueError):
                validate_add_service(self.salon, **kwargs)
        self.assertEqual(Service.objects.count(), 0)
