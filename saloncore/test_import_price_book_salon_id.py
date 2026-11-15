"""Tests for import_price_book --salon-id (bridge to id-selected salon).

The fixture is a tiny hand-written JSON document in the shape of a
real services export — unit logic only, no real salon data.
"""
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)

FIXTURE = [
    {
        "serviceId": "svc-1", "name": "Haircut", "categoryName": "Hair",
        "duration": 60, "gapTime": 0, "price": 50.0, "archived": False,
        "staffCategories": {"prices": []}, "userPrices": [],
    },
]

MODELS = (Salon, ServiceCategory, Service, StaffLevel,
          ServicePrice, PriceChange)


def _write(payload):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(payload, fh)
    fh.close()
    return fh.name


class ImportPriceBookSalonIdTests(TestCase):
    def run_import(self, payload=FIXTURE, **kwargs):
        out = io.StringIO()
        call_command("import_price_book", _write(payload),
                     stdout=out, **kwargs)
        return out.getvalue()

    def test_salon_id_selects_existing_salon(self):
        target = Salon.objects.create(name="Target Salon")
        out = self.run_import(salon_id=target.pk)
        self.assertIn("IMPORT_SUMMARY", out)
        summary = json.loads(
            [ln for ln in out.splitlines()
             if ln.startswith("IMPORT_SUMMARY ")][0][len("IMPORT_SUMMARY "):])
        self.assertEqual(summary["salon"], "Target Salon")
        self.assertEqual(Salon.objects.count(), 1)
        self.assertEqual(ServiceCategory.objects.get().salon, target)
        self.assertEqual(Service.objects.count(), 1)
        self.assertEqual(StaffLevel.objects.get().salon, target)

    def test_salon_id_nonexistent_raises_and_writes_nothing(self):
        with self.assertRaises(CommandError):
            self.run_import(salon_id=999999)
        for model in MODELS:
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def test_salon_id_takes_precedence_over_salon_name(self):
        target = Salon.objects.create(name="Target Salon")
        out = self.run_import(salon="Other Salon", salon_id=target.pk)
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertEqual(Salon.objects.count(), 1)
        self.assertFalse(Salon.objects.filter(name="Other Salon").exists())
        self.assertEqual(ServiceCategory.objects.get().salon, target)

    def test_name_path_still_creates_salon_by_name(self):
        self.run_import(salon="Named Salon")
        self.assertEqual(
            ServiceCategory.objects.get().salon.name, "Named Salon")
        self.assertEqual(Salon.objects.count(), 1)
