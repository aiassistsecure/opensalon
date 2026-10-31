import csv
import io
import json
from decimal import Decimal

from django.test import TestCase

from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from saloncore.price_book_export import (
    EXPORT_FIELDNAMES,
    PRICE_BOOK_FIELDNAMES,
    export_price_book,
    export_price_book_csv,
    price_book_csv,
)


class PriceBookExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=1)
        self.junior = StaffLevel.objects.create(
            salon=self.salon, name="Junior", sort_order=1)
        self.level6 = StaffLevel.objects.create(
            salon=self.salon, name="Level 6", sort_order=2)
        self.service = Service.objects.create(
            category=self.category, name="Single Process Color",
            service_minutes=45, processing_minutes=30,
            finishing_minutes=15)
        self.price_junior = ServicePrice.objects.create(
            service=self.service, staff_level=self.junior,
            amount=Decimal("65.00"))
        self.price_level6 = ServicePrice.objects.create(
            service=self.service, staff_level=self.level6,
            amount=Decimal("85.50"), is_from=True)

    def _other_book(self):
        category = ServiceCategory.objects.create(
            salon=self.other, name="Haircuts")
        service = Service.objects.create(
            category=category, name="Other Cut", service_minutes=30)
        level = StaffLevel.objects.create(salon=self.other, name="Solo")
        ServicePrice.objects.create(
            service=service, staff_level=level, amount=Decimal("40.00"))
        return service

    def test_fieldnames_and_header(self):
        self.assertEqual(
            PRICE_BOOK_FIELDNAMES,
            ["salon_id", "category_id", "category_name", "service_id",
             "service_name", "description", "external_id",
             "service_minutes", "processing_minutes", "finishing_minutes",
             "total_minutes", "service_active", "staff_level_id",
             "staff_level_name", "service_price_id", "amount",
             "is_from", "price_active"],
        )
        self.assertEqual(EXPORT_FIELDNAMES, PRICE_BOOK_FIELDNAMES)
        rows = list(csv.reader(io.StringIO(
            export_price_book_csv(self.salon))))
        self.assertEqual(rows[0], PRICE_BOOK_FIELDNAMES)

    def test_rows_include_level_prices_and_duration_gap(self):
        records = export_price_book(self.salon)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], {
            "salon_id": self.salon.pk,
            "category_id": self.category.pk,
            "category_name": "Color",
            "service_id": self.service.pk,
            "service_name": "Single Process Color",
            "description": "",
            "external_id": "",
            "service_minutes": 45,
            "processing_minutes": 30,
            "finishing_minutes": 15,
            "total_minutes": 90,
            "service_active": True,
            "staff_level_id": self.junior.pk,
            "staff_level_name": "Junior",
            "service_price_id": self.price_junior.pk,
            "amount": "65.00",
            "is_from": False,
            "price_active": True,
        })
        self.assertEqual(records[1]["staff_level_name"], "Level 6")
        self.assertEqual(records[1]["amount"], "85.50")
        self.assertEqual(records[1]["is_from"], True)
        self.assertEqual(json.loads(json.dumps(records)), records)

    def test_deterministic_ordering(self):
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Haircuts", sort_order=0)
        service = Service.objects.create(
            category=category, name="A Cut", service_minutes=30)
        ServicePrice.objects.create(
            service=service, staff_level=self.level6,
            amount=Decimal("50.00"))
        records = export_price_book(self.salon)
        self.assertEqual(
            [(r["category_name"], r["service_name"]) for r in records],
            [("Haircuts", "A Cut"), ("Color", "Single Process Color"),
             ("Color", "Single Process Color")],
        )

    def test_unpriced_service_appears_with_empty_price(self):
        Service.objects.create(
            category=self.category, name="Consultation",
            service_minutes=15)
        records = export_price_book(self.salon)
        unpriced = [r for r in records
                    if r["service_name"] == "Consultation"]
        self.assertEqual(len(unpriced), 1)
        self.assertIsNone(unpriced[0]["staff_level_id"])
        self.assertIsNone(unpriced[0]["service_price_id"])
        self.assertIsNone(unpriced[0]["amount"])

    def test_salon_isolation(self):
        self._other_book()
        records = export_price_book(self.salon)
        self.assertEqual(
            {r["service_name"] for r in records},
            {"Single Process Color"})
        self.assertNotIn("Other Cut", export_price_book_csv(self.salon))
        other_records = export_price_book(self.other)
        self.assertEqual(len(other_records), 1)
        self.assertEqual(other_records[0]["amount"], "40.00")

    def test_csv_matches_list_export_and_alias(self):
        parsed = list(csv.DictReader(io.StringIO(
            export_price_book_csv(self.salon))))
        records = export_price_book(self.salon)
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(int(row["service_id"]), record["service_id"])
            self.assertEqual(row["amount"], record["amount"])
            self.assertEqual(
                row["staff_level_name"], record["staff_level_name"])
            self.assertEqual(
                int(row["total_minutes"]), record["total_minutes"])
        self.assertEqual(
            price_book_csv(self.salon), export_price_book_csv(self.salon))

    def test_empty_book(self):
        empty = Salon.objects.create(name="Empty Salon")
        self.assertEqual(export_price_book(empty), [])
        self.assertEqual(
            export_price_book_csv(empty),
            ",".join(PRICE_BOOK_FIELDNAMES) + "\n",
        )

    def test_read_only(self):
        before = (
            Service.objects.count(), ServicePrice.objects.count(),
            ServiceCategory.objects.count(), StaffLevel.objects.count(),
        )
        export_price_book(self.salon)
        export_price_book_csv(self.salon)
        self.assertEqual(
            (Service.objects.count(), ServicePrice.objects.count(),
             ServiceCategory.objects.count(), StaffLevel.objects.count()),
            before,
        )
