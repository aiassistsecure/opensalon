from decimal import Decimal

from django.test import TestCase

from catalog.models import Product
from catalog.search import search_products
from saloncore.models import Salon


class SearchProductsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def make_product(self, name, sku="", barcode="", salon=None, active=True):
        return Product.objects.create(
            salon=salon or self.salon,
            name=name,
            sku=sku,
            barcode=barcode,
            price=Decimal("24.00"),
            active=active,
        )

    def test_name_match_is_icontains(self):
        product = self.make_product("Lavender Shampoo")
        self.make_product("Conditioner")
        self.assertEqual(list(search_products(self.salon, "shampoo")), [product])
        self.assertEqual(list(search_products(self.salon, "SHAMPOO")), [product])
        self.assertEqual(list(search_products(self.salon, "Lavender Sha")), [product])

    def test_exact_sku_match(self):
        product = self.make_product("Gel", sku="GL-100")
        self.make_product("Wax", sku="WX-200")
        self.assertEqual(list(search_products(self.salon, "GL-100")), [product])

    def test_partial_sku_does_not_match(self):
        self.make_product("Gel", sku="GL-100")
        self.assertEqual(list(search_products(self.salon, "GL-10")), [])
        self.assertEqual(list(search_products(self.salon, "GL-1000")), [])

    def test_exact_barcode_match(self):
        product = self.make_product("Gel", barcode="012345678905")
        self.make_product("Wax", barcode="012345678906")
        self.assertEqual(
            list(search_products(self.salon, "012345678905")), [product]
        )

    def test_barcode_match_is_exact_not_partial(self):
        self.make_product("Gel", barcode="012345678905")
        for partial in ("01234567890", "12345678905", "0123456789050"):
            self.assertEqual(list(search_products(self.salon, partial)), [])

    def test_blank_query_matches_nothing_including_blank_codes(self):
        self.make_product("Gel")  # sku and barcode are blank
        for blank in ("", "   ", None):
            self.assertEqual(list(search_products(self.salon, blank)), [])

    def test_query_is_stripped(self):
        product = self.make_product("Gel", sku="GL-100")
        self.assertEqual(list(search_products(self.salon, "  GL-100  ")), [product])

    def test_cross_salon_isolation(self):
        foreign = self.make_product(
            "Lavender Shampoo", sku="GL-100", barcode="012345678905",
            salon=self.other,
        )
        own = self.make_product("Lavender Conditioner")
        for query in ("Lavender Shampoo", "GL-100", "012345678905"):
            results = list(search_products(self.salon, query))
            self.assertNotIn(foreign, results)
        self.assertEqual(list(search_products(self.salon, "Lavender")), [own])
        self.assertEqual(
            list(search_products(self.other, "GL-100")), [foreign]
        )

    def test_inactive_excluded_by_default(self):
        active = self.make_product("Active Gel", sku="GL-100")
        self.make_product("Retired Gel", sku="GL-200", active=False)
        self.assertEqual(list(search_products(self.salon, "Gel")), [active])
        self.assertEqual(list(search_products(self.salon, "GL-200")), [])

    def test_inactive_included_with_flag(self):
        active = self.make_product("Active Gel")
        retired = self.make_product("Retired Gel", active=False)
        self.assertEqual(
            list(search_products(self.salon, "Gel", include_inactive=True)),
            [active, retired],
        )

    def test_results_ordered_by_name(self):
        shampoo = self.make_product("Shampoo Deluxe")
        mask = self.make_product("Mask Deluxe")
        conditioner = self.make_product("Conditioner Deluxe")
        self.assertEqual(
            list(search_products(self.salon, "Deluxe")),
            [conditioner, mask, shampoo],
        )

    def test_no_match_returns_empty(self):
        self.make_product("Gel", sku="GL-100", barcode="012345678905")
        self.assertEqual(list(search_products(self.salon, "no-such-thing")), [])
