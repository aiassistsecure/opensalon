"""Round-trip regression: export_price_book CSV re-imports cleanly.

Seeds a salon ONLY through the existing JSON importer shape
(synthetic data), exports via ``export_price_book``, re-imports
the CSV into a fresh salon via ``import_price_book``, and asserts
field-level equality — the spike of 2026-10-31 found this leg
hard-failed with "not valid JSON" (RT-M2).
"""
import io
import json
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from saloncore.models import (
    Salon,
    Service,
    ServicePrice,
)
from saloncore.price_book_export import export_price_book_csv

FIXTURE = [
    {
        "serviceId": "svc-cut", "name": "Haircut",
        "categoryName": "Hair", "duration": 60, "gapTime": 10,
        "price": 50.0, "archived": False,
        "internetDescription": "A cut.",
        "staffCategories": {"prices": [
            {"id": "Senior", "price": 70.0},
            {"id": "Junior", "price": 40.0},
        ]},
        "userPrices": [],
    },
    {
        "serviceId": "svc-perm", "name": "Old Perm",
        "categoryName": "Hair", "duration": 90, "gapTime": 0,
        "price": 80.0, "archived": True,
        "staffCategories": {"prices": []}, "userPrices": [],
    },
    {
        "serviceId": "svc-consult", "name": "Consultation",
        "categoryName": "Advice", "duration": 15, "gapTime": 0,
        "archived": False, "userPrices": [],
    },
]


def _write(payload, suffix=".json"):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8")
    if isinstance(payload, str):
        fh.write(payload)
    else:
        json.dump(payload, fh)
    fh.close()
    return fh.name


def _snapshot(salon):
    """Field-level price book of ``salon``, keyed by external_id."""
    book = {}
    services = Service.objects.filter(
        category__salon=salon).select_related("category")
    for service in services:
        prices = sorted(
            (p.staff_level.name, str(p.amount), p.is_from, p.active)
            for p in service.prices.all()
            if p.staff_level.salon_id == salon.pk)
        book[service.external_id or service.name] = {
            "name": service.name,
            "category": service.category.name,
            "description": service.description,
            "external_id": service.external_id,
            "service_minutes": service.service_minutes,
            "processing_minutes": service.processing_minutes,
            "finishing_minutes": service.finishing_minutes,
            "active": service.active,
            "prices": prices,
        }
    return book


class PriceBookRoundTripTests(TestCase):
    def seed_and_export(self):
        call_command("import_price_book", _write(FIXTURE),
                     salon="Source Salon", stdout=io.StringIO())
        return Salon.objects.get(name="Source Salon")

    def test_csv_round_trip_into_fresh_salon(self):
        source = self.seed_and_export()
        # Capture before re-import: services key on external_id
        # globally, so the copy salon's import adopts those rows.
        expected = _snapshot(source)
        csv_path = _write(export_price_book_csv(source), suffix=".csv")
        out = io.StringIO()
        call_command("import_price_book", csv_path,
                     salon="Copy Salon", stdout=out)
        self.assertIn("IMPORT_SUMMARY", out.getvalue())
        copy_salon = Salon.objects.get(name="Copy Salon")
        self.assertEqual(_snapshot(copy_salon), expected)
        # Identity survives: external_ids are the source system's,
        # not the exporting database's internal row ids.
        self.assertEqual(
            set(Service.objects.filter(category__salon=copy_salon)
                .values_list("external_id", flat=True)),
            {"svc-cut", "svc-perm", "svc-consult"})

    def test_csv_detected_by_content_without_extension(self):
        source = self.seed_and_export()
        expected = _snapshot(source)
        path = _write(export_price_book_csv(source), suffix=".txt")
        call_command("import_price_book", path, salon="Copy Salon",
                     stdout=io.StringIO())
        self.assertEqual(
            _snapshot(Salon.objects.get(name="Copy Salon")), expected)

    def test_round_trip_preserves_from_inactive_and_finishing(self):
        source = self.seed_and_export()
        cut = Service.objects.get(external_id="svc-cut")
        cut.finishing_minutes = 5
        cut.save(update_fields=["finishing_minutes"])
        price = ServicePrice.objects.get(
            service=cut, staff_level__name="Senior")
        price.is_from = True
        price.active = False
        price.save(update_fields=["is_from", "active"])
        expected = _snapshot(source)
        csv_path = _write(export_price_book_csv(source), suffix=".csv")
        call_command("import_price_book", csv_path, salon="Copy Salon",
                     stdout=io.StringIO())
        self.assertEqual(
            _snapshot(Salon.objects.get(name="Copy Salon")), expected)
        copied = ServicePrice.objects.get(
            service__external_id="svc-cut",
            service__category__salon__name="Copy Salon",
            staff_level__salon__name="Copy Salon",
            staff_level__name="Senior")
        self.assertEqual(copied.amount, Decimal("70.00"))
        self.assertTrue(copied.is_from)
        self.assertFalse(copied.active)
