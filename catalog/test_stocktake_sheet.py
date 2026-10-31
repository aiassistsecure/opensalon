from decimal import Decimal

from django.test import TestCase

from catalog.models import Product, StockMovement
from catalog.stocktake_sheet import StocktakeSheetRow, stocktake_sheet
from saloncore.models import Salon


class StocktakeSheetTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def make_product(self, name, sku="", barcode="", price="24.00", salon=None, active=True):
        return Product.objects.create(
            salon=salon or self.salon,
            name=name,
            sku=sku,
            barcode=barcode,
            price=Decimal(price),
            active=active,
        )

    def move(self, product, delta, kind=StockMovement.Kind.RECEIVE):
        return StockMovement.objects.create(
            product=product, kind=kind, quantity_delta=delta
        )

    def test_on_hand_is_derived_from_movements(self):
        product = self.make_product(
            "Shampoo", sku="SH-001", barcode="012345678905", price="18.50"
        )
        self.move(product, 10)
        self.move(product, -7, kind=StockMovement.Kind.SALE)
        self.move(product, -1, kind=StockMovement.Kind.ADJUSTMENT)
        rows = stocktake_sheet(self.salon)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertIsInstance(row, StocktakeSheetRow)
        self.assertEqual(row.product, product)
        self.assertEqual(row.name, "Shampoo")
        self.assertEqual(row.sku, "SH-001")
        self.assertEqual(row.barcode, "012345678905")
        self.assertEqual(row.on_hand, 2)
        self.assertEqual(row.current_stock, 2)
        self.assertEqual(row.retail_price, Decimal("18.50"))
        self.assertEqual(row.price, Decimal("18.50"))

    def test_product_with_no_movements_shows_zero(self):
        product = self.make_product("Never Stocked")
        rows = stocktake_sheet(self.salon)
        self.assertEqual([row.product for row in rows], [product])
        self.assertEqual(rows[0].on_hand, 0)

    def test_other_salons_products_are_excluded(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = self.make_product("Foreign", salon=other)
        self.move(foreign, 9)
        own = self.make_product("Own")
        rows = stocktake_sheet(self.salon)
        self.assertEqual([row.product for row in rows], [own])
        rows = stocktake_sheet(other)
        self.assertEqual([row.product for row in rows], [foreign])
        self.assertEqual(rows[0].on_hand, 9)

    def test_rows_ordered_by_name(self):
        conditioner = self.make_product("Conditioner")
        self.move(conditioner, 4)
        shampoo = self.make_product("Shampoo")
        balm = self.make_product("Balm")
        self.move(balm, 1)
        rows = stocktake_sheet(self.salon)
        self.assertEqual(
            [row.product for row in rows], [balm, conditioner, shampoo]
        )
        self.assertEqual([row.name for row in rows], ["Balm", "Conditioner", "Shampoo"])
        self.assertEqual([row.on_hand for row in rows], [1, 4, 0])

    def test_inactive_products_are_excluded(self):
        retired = self.make_product("Retired", active=False)
        self.move(retired, 12)
        current = self.make_product("Current")
        rows = stocktake_sheet(self.salon)
        self.assertEqual([row.product for row in rows], [current])

    def test_empty_salon_has_empty_sheet(self):
        self.assertEqual(stocktake_sheet(self.salon), [])
