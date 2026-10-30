"""Tests for the import_price_book management command.

The fixture below is a tiny hand-written JSON document in the shape of
a real services export — unit logic only, no real salon data.
"""
import io
import json
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import (
    PriceChange,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)

FIXTURE = [
    {
        "serviceId": "svc-1", "name": "Haircut", "categoryName": "Hair",
        "categoryId": "cat-hair", "duration": 60, "gapTime": 0,
        "price": 50.0, "archived": False,
        "internetDescription": "A cut.",
        "staffCategories": {"prices": [
            {"id": "lvl-senior", "price": 70.0},
            {"id": "lvl-junior", "price": 40.0},
        ]},
        "userPrices": [{"userRef": "person-1", "price": 999.0}],
    },
    {
        "serviceId": "svc-2", "name": "Old Perm", "categoryName": "Hair",
        "categoryId": "cat-hair", "duration": 90, "price": 80.0,
        "archived": True, "staffCategories": {"prices": []},
        "userPrices": [],
    },
    {"serviceId": "svc-3", "duration": 10, "price": 1.0},  # no name: skipped
]

STAFF_FIXTURE = [
    {"staffId": "person-1", "userId": "person-1",
     "staffCategoryId": "lvl-senior", "staffCategoryName": "Senior"},
    {"staffId": "person-2", "userId": "person-2",
     "staffCategoryId": "lvl-junior", "staffCategoryName": "Junior"},
]


def _write(payload):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fh)
    fh.close()
    return fh.name


class ImportPriceBookTests(TestCase):
    def run_import(self, payload=FIXTURE, **kwargs):
        out = io.StringIO()
        call_command("import_price_book", _write(payload),
                     stdout=out, **kwargs)
        return out.getvalue()

    def test_imports_categories_services_levels_and_prices(self):
        out = self.run_import()
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertEqual(ServiceCategory.objects.count(), 1)
        self.assertEqual(Service.objects.count(), 2)
        # Base + the two staff-category levels from the fixture.
        self.assertEqual(StaffLevel.objects.count(), 3)
        # 2 base prices + 2 level prices; the per-person price is skipped.
        self.assertEqual(ServicePrice.objects.count(), 4)
        cut = Service.objects.get(name="Haircut")
        self.assertEqual(cut.service_minutes, 60)
        self.assertEqual(cut.description, "A cut.")
        base = ServicePrice.objects.get(
            service=cut, staff_level__name="Base")
        self.assertEqual(base.amount, Decimal("50.0"))

    def test_archived_service_imports_inactive(self):
        self.run_import()
        self.assertFalse(Service.objects.get(name="Old Perm").active)

    def test_rerun_is_idempotent_no_duplicates(self):
        self.run_import()
        self.run_import()
        self.assertEqual(Service.objects.count(), 2)
        self.assertEqual(ServiceCategory.objects.count(), 1)
        self.assertEqual(StaffLevel.objects.count(), 3)
        self.assertEqual(ServicePrice.objects.count(), 4)
        self.assertEqual(PriceChange.objects.count(), 0)

    def test_rerun_with_changed_price_updates_and_audits(self):
        self.run_import()
        changed = json.loads(json.dumps(FIXTURE))
        changed[0]["price"] = 55.0
        self.run_import(payload=changed)
        base = ServicePrice.objects.get(
            service__name="Haircut", staff_level__name="Base")
        self.assertEqual(base.amount, Decimal("55.0"))
        self.assertEqual(ServicePrice.objects.count(), 4)
        change = PriceChange.objects.get(service_price=base)
        self.assertEqual(change.old_amount, Decimal("50.0"))
        self.assertEqual(change.new_amount, Decimal("55.0"))
        self.assertEqual(change.changed_by, "import_price_book")

    def test_staff_file_resolves_level_names_and_skips_individuals(self):
        payload = json.loads(json.dumps(FIXTURE))
        payload[0]["staffCategories"]["prices"].append(
            {"id": "person-1", "price": 123.0})  # an individual, not a level
        self.run_import(payload=payload, staff=_write(STAFF_FIXTURE))
        names = set(StaffLevel.objects.values_list("name", flat=True))
        self.assertEqual(names, {"Base", "Senior", "Junior"})
        senior = ServicePrice.objects.get(
            service__name="Haircut", staff_level__name="Senior")
        self.assertEqual(senior.amount, Decimal("70.0"))

    def test_salon_option_scopes_the_import(self):
        self.run_import(salon="Other Salon")
        self.assertEqual(
            ServiceCategory.objects.get().salon.name, "Other Salon")

    def test_missing_file_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command("import_price_book", "/nonexistent/services.json")

    def test_invalid_json_raises_command_error(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False)
        fh.write("{not json")
        fh.close()
        with self.assertRaises(CommandError):
            call_command("import_price_book", fh.name)
