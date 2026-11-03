from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory
from saloncore.search import search_services


class SearchServicesTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.hair = ServiceCategory.objects.create(
            salon=self.salon, name="Hair", sort_order=1)
        self.color = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=2)
        self.other_cat = ServiceCategory.objects.create(
            salon=self.other, name="Hair", sort_order=1)

    def make_service(self, name, category=None, active=True, **kw):
        return Service.objects.create(
            category=category or self.hair, name=name,
            service_minutes=kw.pop("service_minutes", 30),
            active=active, **kw)

    def test_name_match_is_icontains(self):
        svc = self.make_service("Women's Haircut")
        self.make_service("Balayage", category=self.color)
        self.assertEqual(list(search_services(self.salon, "haircut")), [svc])
        self.assertEqual(list(search_services(self.salon, "HAIRCUT")), [svc])
        self.assertEqual(list(search_services(self.salon, "Hairc")), [svc])

    def test_category_name_match(self):
        cut = self.make_service("Women's Haircut")
        trim = self.make_service("Trim")
        balayage = self.make_service("Balayage", category=self.color)
        # "hair" matches the Haircut name AND the Hair category;
        # results order by name within the category.
        self.assertEqual(
            list(search_services(self.salon, "Hair")), [trim, cut])
        self.assertEqual(
            list(search_services(self.salon, "color")), [balayage])
        self.assertEqual(
            list(search_services(self.salon, "COLOR")), [balayage])

    def test_blank_query_matches_nothing(self):
        self.make_service("Haircut")
        for blank in ("", "   ", None):
            self.assertEqual(list(search_services(self.salon, blank)), [])

    def test_query_is_stripped(self):
        svc = self.make_service("Haircut")
        self.assertEqual(
            list(search_services(self.salon, "  Haircut  ")), [svc])

    def test_cross_salon_isolation(self):
        foreign = self.make_service(
            "Haircut", category=self.other_cat)
        own = self.make_service("Haircut Deluxe")
        self.assertEqual(
            list(search_services(self.salon, "Haircut")), [own])
        self.assertEqual(
            list(search_services(self.other, "Haircut")), [foreign])

    def test_inactive_excluded_by_default(self):
        active = self.make_service("Active Cut")
        self.make_service("Retired Cut", active=False)
        self.assertEqual(list(search_services(self.salon, "Cut")), [active])

    def test_inactive_included_with_flag(self):
        active = self.make_service("Active Cut")
        retired = self.make_service("Retired Cut", active=False)
        self.assertEqual(
            list(search_services(
                self.salon, "Cut", include_inactive=True)),
            [active, retired])

    def test_results_ordered_by_category_then_name(self):
        balayage = self.make_service("Balayage Deluxe", category=self.color)
        cut_b = self.make_service("B Deluxe Cut")
        cut_a = self.make_service("A Deluxe Cut")
        # Hair (sort 1) before Color (sort 2); name order within.
        self.assertEqual(
            list(search_services(self.salon, "Deluxe")),
            [cut_a, cut_b, balayage])

    def test_no_match_returns_empty(self):
        self.make_service("Haircut")
        self.assertEqual(
            list(search_services(self.salon, "no-such-thing")), [])

    def test_result_carries_category(self):
        svc = self.make_service("Balayage", category=self.color)
        found = list(search_services(self.salon, "Balayage"))
        self.assertEqual(found, [svc])
        self.assertEqual(found[0].category, self.color)
