import csv
import io
from decimal import Decimal

from django.test import TestCase

from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from saloncore.structure_export import (
    SERVICE_CATEGORY_FIELDNAMES,
    STAFF_LEVEL_FIELDNAMES,
    export_service_categories,
    export_service_categories_csv,
    export_staff_levels,
    export_staff_levels_csv,
    export_structure,
    export_structure_csv,
    service_categories_csv,
    staff_levels_csv,
    structure_csv,
)


class StructureExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def _category(self, salon=None, **kw):
        kw.setdefault("name", "Color")
        return ServiceCategory.objects.create(salon=salon or self.salon, **kw)

    def _level(self, salon=None, **kw):
        kw.setdefault("name", "Level 6")
        return StaffLevel.objects.create(salon=salon or self.salon, **kw)

    def test_fieldnames(self):
        expected = ["id", "salon_id", "name", "sort_order", "active"]
        self.assertEqual(SERVICE_CATEGORY_FIELDNAMES, expected)
        self.assertEqual(STAFF_LEVEL_FIELDNAMES, expected)

    def test_category_rows_match_created_records(self):
        cat = self._category(sort_order=2, active=False)
        self.assertEqual(
            export_service_categories(self.salon),
            [{"id": cat.pk, "salon_id": self.salon.pk, "name": "Color",
              "sort_order": 2, "active": False}],
        )

    def test_level_rows_match_created_records(self):
        level = self._level(sort_order=6, active=True)
        self.assertEqual(
            export_staff_levels(self.salon),
            [{"id": level.pk, "salon_id": self.salon.pk, "name": "Level 6",
              "sort_order": 6, "active": True}],
        )

    def test_orphan_category_without_services_still_appears(self):
        used = self._category(name="Haircuts")
        Service.objects.create(
            category=used, name="Cut", service_minutes=45)
        orphan = self._category(name="Empty Shelf", sort_order=9)
        rows = export_service_categories(self.salon)
        self.assertEqual([r["id"] for r in rows], [used.pk, orphan.pk])

    def test_orphan_level_without_prices_still_appears(self):
        used = self._level(name="Junior")
        category = self._category()
        service = Service.objects.create(
            category=category, name="Cut", service_minutes=45)
        ServicePrice.objects.create(
            service=service, staff_level=used, amount=Decimal("50.00"))
        orphan = self._level(name="Unused Tier", sort_order=9)
        rows = export_staff_levels(self.salon)
        self.assertEqual([r["id"] for r in rows], [used.pk, orphan.pk])

    def test_ordering_is_sort_order_then_name(self):
        self._category(name="Zeta", sort_order=1)
        self._category(name="Alpha", sort_order=1)
        self._category(name="First", sort_order=0)
        names = [r["name"] for r in export_service_categories(self.salon)]
        self.assertEqual(names, ["First", "Alpha", "Zeta"])
        self._level(name="Zeta", sort_order=1)
        self._level(name="Alpha", sort_order=1)
        self._level(name="First", sort_order=0)
        names = [r["name"] for r in export_staff_levels(self.salon)]
        self.assertEqual(names, ["First", "Alpha", "Zeta"])

    def test_salon_isolation(self):
        self._category()
        self._level()
        self._category(salon=self.other, name="Theirs")
        self._level(salon=self.other, name="Theirs")
        self.assertEqual(len(export_service_categories(self.salon)), 1)
        self.assertEqual(len(export_staff_levels(self.salon)), 1)
        self.assertEqual(
            export_service_categories(self.other)[0]["name"], "Theirs")
        self.assertEqual(
            export_staff_levels(self.other)[0]["name"], "Theirs")

    def test_empty_salon_exports_empty(self):
        self.assertEqual(export_service_categories(self.salon), [])
        self.assertEqual(export_staff_levels(self.salon), [])
        self.assertEqual(
            export_structure(self.salon),
            {"service_categories": [], "staff_levels": []},
        )
        rows = list(csv.reader(io.StringIO(
            export_service_categories_csv(self.salon))))
        self.assertEqual(rows, [SERVICE_CATEGORY_FIELDNAMES])
        rows = list(csv.reader(io.StringIO(
            export_staff_levels_csv(self.salon))))
        self.assertEqual(rows, [STAFF_LEVEL_FIELDNAMES])

    def test_csv_agrees_with_dict_export(self):
        self._category(sort_order=3, active=False)
        self._level(sort_order=4)
        cat_rows = list(csv.DictReader(io.StringIO(
            export_service_categories_csv(self.salon))))
        self.assertEqual(len(cat_rows), 1)
        self.assertEqual(cat_rows[0]["name"], "Color")
        self.assertEqual(cat_rows[0]["sort_order"], "3")
        self.assertEqual(cat_rows[0]["active"], "False")
        level_rows = list(csv.DictReader(io.StringIO(
            export_staff_levels_csv(self.salon))))
        self.assertEqual(len(level_rows), 1)
        self.assertEqual(level_rows[0]["sort_order"], "4")
        self.assertEqual(level_rows[0]["active"], "True")

    def test_structure_combines_both_kinds(self):
        cat = self._category()
        level = self._level()
        structure = export_structure(self.salon)
        self.assertEqual(
            [r["id"] for r in structure["service_categories"]], [cat.pk])
        self.assertEqual(
            [r["id"] for r in structure["staff_levels"]], [level.pk])
        combined = export_structure_csv(self.salon)
        self.assertEqual(
            combined,
            export_service_categories_csv(self.salon)
            + "\n"
            + export_staff_levels_csv(self.salon),
        )

    def test_aliases(self):
        self.assertIs(service_categories_csv, export_service_categories_csv)
        self.assertIs(staff_levels_csv, export_staff_levels_csv)
        self.assertIs(structure_csv, export_structure_csv)
