from django.test import TestCase

from saloncore.models import Salon


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
