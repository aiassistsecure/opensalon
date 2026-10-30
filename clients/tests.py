from django.test import TestCase

from clients.models import Client
from saloncore.models import Salon


class ClientModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def test_creation_and_salon_fk(self):
        client = Client.objects.create(
            salon=self.salon,
            first_name="Test",
            last_name="Example",
            email="test.example@example.com",
            phone="555-0100",
        )
        self.assertEqual(client.salon, self.salon)
        self.assertIn(client, list(self.salon.clients.all()))
        self.assertTrue(client.active)
        self.assertIsNotNone(client.created_at)

    def test_opt_ins_default_false(self):
        client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example"
        )
        client.refresh_from_db()
        self.assertFalse(client.sms_opt_in)
        self.assertFalse(client.email_opt_in)

    def test_opt_in_true_case(self):
        client = Client.objects.create(
            salon=self.salon,
            first_name="Opted",
            last_name="In",
            sms_opt_in=True,
            email_opt_in=True,
        )
        client.refresh_from_db()
        self.assertTrue(client.sms_opt_in)
        self.assertTrue(client.email_opt_in)

    def test_str_is_first_last(self):
        client = Client(salon=self.salon, first_name="Test", last_name="Example")
        self.assertEqual(str(client), "Test Example")

    def test_ordering_by_last_then_first(self):
        Client.objects.create(
            salon=self.salon, first_name="Zoe", last_name="Smith"
        )
        Client.objects.create(
            salon=self.salon, first_name="Amy", last_name="Smith"
        )
        Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Adams"
        )
        names = list(
            Client.objects.values_list("last_name", "first_name")
        )
        self.assertEqual(
            names,
            [("Adams", "Bob"), ("Smith", "Amy"), ("Smith", "Zoe")],
        )
