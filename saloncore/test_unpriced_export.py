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
from saloncore.unpriced_export import (
    EXPORT_FIELDNAMES,
    UNPRICED_EXPORT_FIELDNAMES,
    UNPRICED_FIELDNAMES,
    export_fully_unpriced_services,
    export_fully_unpriced_services_csv,
    export_unpriced_services,
    export_unpriced_services_csv,
    unpriced_csv,
)


class UnpricedExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint")
        self.other = Salon.objects.create(name="Other")
        self.cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.other_cat = ServiceCategory.objects.create(
            salon=self.other, name="Hair")
        self.junior = StaffLevel.objects.create(
            salon=self.salon, name="Junior", sort_order=1)
        self.senior = StaffLevel.objects.create(
            salon=self.salon, name="Senior", sort_order=2)
        self.unpriced = Service.objects.create(
            category=self.cat, name="Unpriced Cut", service_minutes=30)
        self.full = Service.objects.create(
            category=self.cat, name="Full Cut", service_minutes=30)
        self.partial = Service.objects.create(
            category=self.cat, name="Partial Cut", service_minutes=30)
        for level in (self.junior, self.senior):
            ServicePrice.objects.create(
                service=self.full, staff_level=level,
                amount=Decimal("50.00"))
        ServicePrice.objects.create(
            service=self.partial, staff_level=self.junior,
            amount=Decimal("40.00"))

    def test_fieldnames_and_header(self):
        expected = [
            "salon_id", "service_id", "service_name", "category_id",
            "category_name", "missing_level_ids", "missing_level_names",
            "missing_level_count",
        ]
        self.assertEqual(UNPRICED_FIELDNAMES, expected)
        self.assertEqual(EXPORT_FIELDNAMES, UNPRICED_FIELDNAMES)
        self.assertEqual(UNPRICED_EXPORT_FIELDNAMES, UNPRICED_FIELDNAMES)
        rows = list(csv.reader(io.StringIO(
            export_unpriced_services_csv(self.salon))))
        self.assertEqual(rows[0], UNPRICED_FIELDNAMES)

    def test_fully_unpriced_row_flattened(self):
        records = export_unpriced_services(self.salon)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0], {
            "salon_id": self.salon.pk,
            "service_id": self.unpriced.pk,
            "service_name": "Unpriced Cut",
            "category_id": self.cat.pk,
            "category_name": "Hair",
            "missing_level_ids": f"{self.junior.pk};{self.senior.pk}",
            "missing_level_names": "Junior;Senior",
            "missing_level_count": 2,
        })
        self.assertEqual(json.loads(json.dumps(records)), records)
        self.assertEqual(
            export_fully_unpriced_services(self.salon), records)

    def test_per_level_export(self):
        records = export_unpriced_services(
            self.salon, staff_level=self.senior)
        self.assertEqual(
            [r["service_name"] for r in records],
            ["Partial Cut", "Unpriced Cut"])
        partial = records[0]
        self.assertEqual(partial["missing_level_ids"], str(self.senior.pk))
        self.assertEqual(partial["missing_level_names"], "Senior")
        self.assertEqual(partial["missing_level_count"], 1)
        junior = export_unpriced_services(
            self.salon, staff_level=self.junior)
        self.assertEqual([r["service_name"] for r in junior], ["Unpriced Cut"])

    def test_priced_service_excluded_and_salon_isolation(self):
        Service.objects.create(
            category=self.other_cat, name="Other Unpriced",
            service_minutes=30)
        records = export_unpriced_services(self.salon)
        self.assertNotIn("Full Cut", [r["service_name"] for r in records])
        self.assertNotIn("Other Unpriced", [r["service_name"] for r in records])
        other = export_unpriced_services(self.other)
        self.assertEqual([r["service_name"] for r in other], ["Other Unpriced"])
        self.assertEqual(other[0]["salon_id"], self.other.pk)

    def test_csv_matches_list_and_aliases(self):
        parsed = list(csv.DictReader(io.StringIO(
            export_unpriced_services_csv(self.salon))))
        records = export_unpriced_services(self.salon)
        self.assertEqual(len(parsed), len(records))
        for row, record in zip(parsed, records):
            self.assertEqual(int(row["service_id"]), record["service_id"])
            self.assertEqual(
                row["missing_level_ids"], record["missing_level_ids"])
            self.assertEqual(
                int(row["missing_level_count"]),
                record["missing_level_count"])
        self.assertEqual(
            unpriced_csv(self.salon),
            export_unpriced_services_csv(self.salon))
        self.assertEqual(
            export_fully_unpriced_services_csv(self.salon),
            export_unpriced_services_csv(self.salon))

    def test_empty_and_foreign_level(self):
        empty = Salon.objects.create(name="Empty")
        self.assertEqual(export_unpriced_services(empty), [])
        self.assertEqual(
            export_unpriced_services_csv(empty),
            ",".join(UNPRICED_FIELDNAMES) + "\n")
        foreign = StaffLevel.objects.create(salon=self.other, name="Foreign")
        with self.assertRaises(ValueError):
            export_unpriced_services(self.salon, staff_level=foreign)

    def test_read_only(self):
        before = (
            Service.objects.count(), ServicePrice.objects.count(),
            ServiceCategory.objects.count(), StaffLevel.objects.count(),
        )
        export_unpriced_services(self.salon)
        export_unpriced_services(self.salon, staff_level=self.senior)
        export_unpriced_services_csv(self.salon)
        export_fully_unpriced_services(self.salon)
        export_fully_unpriced_services_csv(self.salon)
        self.assertEqual(
            (Service.objects.count(), ServicePrice.objects.count(),
             ServiceCategory.objects.count(), StaffLevel.objects.count()),
            before)
