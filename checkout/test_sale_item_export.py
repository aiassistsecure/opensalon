"""SaleItem verbatim export: stored rows, every concrete field."""
import csv
import datetime
import io
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from catalog.models import Product
from checkout.models import Sale, SaleItem
from checkout.sale_item_export import (
    EXPORT_FIELDNAMES,
    SALE_ITEM_EXPORT_FIELDNAMES,
    export_sale_items,
    export_sale_items_csv,
    sale_item_export_row,
    sale_items_csv,
)
from saloncore.models import Salon, Service, ServiceCategory


class SaleItemExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Item Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.day = datetime.date(2026, 10, 3)
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", price=Decimal("24.00"))

    def _at(self, day, hour=12):
        return timezone.make_aware(
            datetime.datetime.combine(day, datetime.time(hour, 0)),
            datetime.timezone.utc)

    def _sale(self, salon=None, day=None):
        sale = Sale.objects.create(
            salon=salon or self.salon, status=Sale.Status.COMPLETED)
        if day is not None:
            Sale.objects.filter(pk=sale.pk).update(
                created_at=self._at(day))
            sale.refresh_from_db()
        return sale

    def _items(self, sale=None):
        sale = sale or self._sale()
        service_item = SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, service=self.service,
            description="Haircut, deluxe", quantity=1,
            unit_price=Decimal("85.00"),
            discount_amount=Decimal("5.00"))
        product_item = SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, product=self.product,
            description="Shampoo", quantity=2,
            unit_price=Decimal("24.5"))
        series_item = SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERIES,
            description="Blowout Series x4", quantity=1,
            unit_price=Decimal("200.00"))
        return [service_item, product_item, series_item]

    def test_fieldnames_guard_against_concrete_fields(self):
        expected = [
            field.attname for field in SaleItem._meta.concrete_fields
        ]
        self.assertEqual(SALE_ITEM_EXPORT_FIELDNAMES, expected)
        self.assertEqual(EXPORT_FIELDNAMES, SALE_ITEM_EXPORT_FIELDNAMES)
        self.assertNotIn("provider_reference", SALE_ITEM_EXPORT_FIELDNAMES)
        self.assertIs(sale_items_csv, export_sale_items_csv)

    def test_rows_verbatim_every_field(self):
        items = self._items()
        records = export_sale_items(self.salon)
        self.assertEqual([r["id"] for r in records],
                         [item.pk for item in items])
        for record in records:
            self.assertEqual(list(record.keys()),
                             SALE_ITEM_EXPORT_FIELDNAMES)
        self.assertEqual(records[0], {
            "id": items[0].pk, "sale_id": items[0].sale_id,
            "kind": "service", "service_id": self.service.pk,
            "product_id": None, "description": "Haircut, deluxe",
            "quantity": 1, "unit_price": "85.00",
            "discount_amount": "5.00"})
        self.assertEqual(records[1]["product_id"], self.product.pk)
        self.assertIsNone(records[1]["service_id"])
        self.assertEqual(records[1]["unit_price"], "24.50")
        self.assertEqual(records[1]["discount_amount"], "0.00")
        self.assertIsNone(records[2]["service_id"])
        self.assertIsNone(records[2]["product_id"])
        self.assertEqual(records[2]["kind"], "series")
        self.assertEqual(sale_item_export_row(items[0]), records[0])

    def test_csv_agrees_with_dict_export(self):
        self._items()
        text = export_sale_items_csv(self.salon)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], SALE_ITEM_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        records = export_sale_items(self.salon)
        self.assertEqual(len(parsed), len(records))
        for parsed_row, record in zip(parsed, records):
            for key in SALE_ITEM_EXPORT_FIELDNAMES:
                exp = "" if record[key] is None else str(record[key])
                self.assertEqual(parsed_row[key], exp)
        self.assertEqual(parsed[0]["description"], "Haircut, deluxe")

    def test_salon_scoping_empty_and_none(self):
        self._items()
        self._items(sale=self._sale(salon=self.other))
        self.assertEqual(len(export_sale_items(self.salon)), 3)
        self.assertEqual(len(export_sale_items(self.other)), 3)
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_sale_items(empty), [])
        self.assertEqual(
            export_sale_items_csv(empty),
            ",".join(SALE_ITEM_EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(export_sale_items(None), [])
        self.assertEqual(
            export_sale_items_csv(None),
            ",".join(SALE_ITEM_EXPORT_FIELDNAMES) + "\n")

    def test_date_range_filters_on_sale_created_at(self):
        in_range = self._items(sale=self._sale(day=self.day))
        self._items(sale=self._sale(
            day=self.day - datetime.timedelta(days=1)))
        next_day = self._items(sale=self._sale(
            day=self.day + datetime.timedelta(days=1)))
        rows = export_sale_items(self.salon, self.day, self.day)
        self.assertEqual([r["id"] for r in rows],
                         [item.pk for item in in_range])
        rows = export_sale_items(
            self.salon, self.day, self.day + datetime.timedelta(days=1))
        self.assertEqual([r["id"] for r in rows],
                         [i.pk for i in in_range + next_day])
        # Single-day default when date_to is omitted.
        self.assertEqual(
            [r["id"] for r in export_sale_items(self.salon, self.day)],
            [item.pk for item in in_range])

    def test_sale_filter_default_none_is_unchanged(self):
        self._items()
        self._items()
        default = export_sale_items(self.salon)
        self.assertEqual(len(default), 6)
        self.assertEqual(
            export_sale_items(self.salon, sale=None), default)
        self.assertEqual(
            export_sale_items_csv(self.salon, sale=None),
            export_sale_items_csv(self.salon))

    def test_sale_filter_only_that_sale(self):
        first = self._items()
        second = self._items()
        rows = export_sale_items(self.salon, sale=first[0].sale)
        self.assertEqual([r["id"] for r in rows],
                         [item.pk for item in first])
        self.assertTrue(all(r["sale_id"] == first[0].sale_id
                            for r in rows))
        parsed = list(csv.DictReader(io.StringIO(
            export_sale_items_csv(self.salon, sale=second[0].sale))))
        self.assertEqual([int(r["id"]) for r in parsed],
                         [item.pk for item in second])

    def test_sale_filter_date_window_still_applies(self):
        items = self._items(sale=self._sale(day=self.day))
        other_day = self.day + datetime.timedelta(days=5)
        self.assertEqual(
            export_sale_items(self.salon, other_day, other_day,
                              sale=items[0].sale), [])
        self.assertEqual(
            export_sale_items_csv(self.salon, other_day, other_day,
                                  sale=items[0].sale),
            ",".join(SALE_ITEM_EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(
            [r["id"] for r in export_sale_items(
                self.salon, self.day, self.day, sale=items[0].sale)],
            [item.pk for item in items])

    def test_sale_filter_other_salon_sale_is_empty(self):
        own = self._items()
        theirs = self._items(sale=self._sale(salon=self.other))
        self.assertEqual(
            export_sale_items(self.salon, sale=theirs[0].sale), [])
        self.assertEqual(
            export_sale_items_csv(self.salon, sale=theirs[0].sale),
            ",".join(SALE_ITEM_EXPORT_FIELDNAMES) + "\n")
        self.assertEqual(
            [r["id"] for r in export_sale_items(
                self.other, sale=theirs[0].sale)],
            [item.pk for item in theirs])
        self.assertEqual(
            [r["id"] for r in export_sale_items(
                self.salon, sale=own[0].sale)],
            [item.pk for item in own])

    def test_reversed_range_and_read_only(self):
        items = self._items(sale=self._sale(day=self.day))
        later = self.day + datetime.timedelta(days=1)
        self.assertEqual(export_sale_items(self.salon, later, self.day), [])
        self.assertEqual(
            export_sale_items_csv(self.salon, later, self.day),
            ",".join(SALE_ITEM_EXPORT_FIELDNAMES) + "\n")
        export_sale_items(self.salon)
        export_sale_items_csv(self.salon)
        self.assertEqual(SaleItem.objects.count(), len(items))
        items[0].refresh_from_db()
        self.assertEqual(items[0].unit_price, Decimal("85.00"))
