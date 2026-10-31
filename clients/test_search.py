from django.test import TestCase

from clients.models import Client
from clients.search import search_clients
from saloncore.models import Salon


class SearchClientsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other_salon = Salon.objects.create(name="Other Salon")
        self.amy = Client.objects.create(
            salon=self.salon,
            first_name="Amy",
            last_name="Smith",
            email="amy.smith@example.com",
            phone="555-0101",
        )
        self.zoe = Client.objects.create(
            salon=self.salon,
            first_name="Zoe",
            last_name="Smith",
            email="zoe@example.net",
            phone="555-0102",
        )
        self.bob = Client.objects.create(
            salon=self.salon,
            first_name="Bob",
            last_name="Adams",
            email="bob@sample.org",
            phone="555-0199",
        )
        self.other = Client.objects.create(
            salon=self.other_salon,
            first_name="Amy",
            last_name="Smith",
            email="amy.smith@example.com",
            phone="555-0101",
        )

    def results(self, query, salon=None):
        return list(search_clients(salon or self.salon, query))

    def test_matches_first_name_case_insensitive_contains(self):
        self.assertEqual(self.results("amy"), [self.amy])
        self.assertEqual(self.results("AMY"), [self.amy])
        self.assertEqual(self.results("zo"), [self.zoe])

    def test_matches_last_name_case_insensitive_contains(self):
        self.assertEqual(self.results("smith"), [self.amy, self.zoe])
        self.assertEqual(self.results("DAM"), [self.bob])

    def test_matches_email_case_insensitive_contains(self):
        self.assertEqual(self.results("EXAMPLE.COM"), [self.amy])
        self.assertEqual(self.results("sample.org"), [self.bob])

    def test_matches_phone_contains(self):
        self.assertEqual(self.results("0199"), [self.bob])
        self.assertEqual(self.results("555-010"), [self.amy, self.zoe])

    def test_no_match_returns_empty(self):
        self.assertEqual(self.results("no-such-text"), [])

    def test_cross_salon_isolation_on_match(self):
        # Identical name/email/phone exists in the other salon.
        self.assertEqual(self.results("amy"), [self.amy])
        self.assertNotIn(self.other, self.results("smith"))
        self.assertEqual(
            self.results("amy", salon=self.other_salon), [self.other]
        )

    def test_empty_query_returns_only_salon_clients_ordered(self):
        expected = [self.bob, self.amy, self.zoe]
        self.assertEqual(self.results(""), expected)
        self.assertEqual(self.results("   "), expected)
        self.assertEqual(self.results(None), expected)

    def test_ordering_is_last_then_first(self):
        self.assertEqual(
            self.results("smith"), [self.amy, self.zoe]
        )
        self.assertEqual(
            [(c.last_name, c.first_name) for c in self.results("")],
            [("Adams", "Bob"), ("Smith", "Amy"), ("Smith", "Zoe")],
        )

    def test_returns_queryset(self):
        qs = search_clients(self.salon, "amy")
        self.assertEqual(qs.model, Client)
        self.assertEqual(list(qs), [self.amy])
