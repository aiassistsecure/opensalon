from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory


class SalonModelTests(TestCase):
    def test_creation_with_defaults(self):
        salon = Salon.objects.create(name="Mint On The Avenue")
        self.assertEqual(salon.timezone, "UTC")
        self.assertEqual(salon.currency, "USD")
        self.assertIsNotNone(salon.created_at)
        self.assertIsNotNone(salon.updated_at)

    def test_explicit_timezone_and_currency_stored(self):
        salon = Salon.objects.create(
            name="Example Salon",
            timezone="America/New_York",
            currency="EUR",
        )
        salon.refresh_from_db()
        self.assertEqual(salon.timezone, "America/New_York")
        self.assertEqual(salon.currency, "EUR")

    def test_str_returns_name(self):
        salon = Salon(name="Str Salon")
        self.assertEqual(str(salon), "Str Salon")

    def test_ordering_by_name(self):
        Salon.objects.create(name="Zebra Cuts")
        Salon.objects.create(name="Alpha Styles")
        Salon.objects.create(name="Mint On The Avenue")
        names = list(Salon.objects.values_list("name", flat=True))
        self.assertEqual(names, ["Alpha Styles", "Mint On The Avenue", "Zebra Cuts"])

    def test_updated_at_changes_on_save(self):
        salon = Salon.objects.create(name="Timestamp Salon")
        first_updated = salon.updated_at
        salon.name = "Timestamp Salon Renamed"
        salon.save()
        salon.refresh_from_db()
        self.assertGreaterEqual(salon.updated_at, first_updated)


class ServiceCategoryModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")

    def test_category_creation_and_salon_fk(self):
        category = ServiceCategory.objects.create(name="Haircuts", salon=self.salon)
        self.assertEqual(category.salon, self.salon)
        self.assertIn(category, list(self.salon.service_categories.all()))
        self.assertEqual(str(category), "Haircuts")

    def test_category_defaults(self):
        category = ServiceCategory.objects.create(name="Color", salon=self.salon)
        self.assertEqual(category.sort_order, 0)
        self.assertTrue(category.active)

    def test_category_ordering_by_sort_order(self):
        ServiceCategory.objects.create(name="Zulu", salon=self.salon, sort_order=2)
        ServiceCategory.objects.create(name="Alpha", salon=self.salon, sort_order=1)
        ServiceCategory.objects.create(name="Beta", salon=self.salon, sort_order=1)
        names = list(ServiceCategory.objects.values_list("name", flat=True))
        self.assertEqual(names, ["Alpha", "Beta", "Zulu"])


class ServiceModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.category = ServiceCategory.objects.create(name="Color", salon=self.salon)

    def test_service_creation_with_segments(self):
        service = Service.objects.create(
            name="Single Process Color",
            category=self.category,
            description="Root color",
            service_minutes=45,
            processing_minutes=30,
            finishing_minutes=15,
        )
        self.assertEqual(service.category, self.category)
        self.assertIn(service, list(self.category.services.all()))
        self.assertEqual(str(service), "Single Process Color")
        self.assertEqual(service.description, "Root color")

    def test_total_minutes_sums_all_three(self):
        service = Service(
            name="Balayage",
            category=self.category,
            service_minutes=60,
            processing_minutes=45,
            finishing_minutes=20,
        )
        self.assertEqual(service.total_minutes, 125)

    def test_processing_and_finishing_default_zero(self):
        service = Service.objects.create(
            name="Haircut", category=self.category, service_minutes=60
        )
        service.refresh_from_db()
        self.assertEqual(service.processing_minutes, 0)
        self.assertEqual(service.finishing_minutes, 0)
        self.assertEqual(service.total_minutes, 60)

    def test_service_active_defaults_true(self):
        service = Service.objects.create(
            name="Blowout", category=self.category, service_minutes=45
        )
        self.assertTrue(service.active)
