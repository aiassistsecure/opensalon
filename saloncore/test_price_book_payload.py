"""TF-10: verbatim source-record retention for the price book.

``Service.payload`` mirrors ``Client.payload`` /
``Appointment.payload`` / ``Product.payload``: the importer
stores the whole source record, the exporter includes it only
when non-empty, and an export-shape record's own payload is
restored as-is (never re-wrapped), so import -> export ->
re-import returns it unchanged. Synthetic fixtures only.
"""
import csv
import io
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from saloncore.models import Salon, Service
from saloncore.price_book_export import (
    PRICE_BOOK_FIELDNAMES,
    export_price_book,
    export_price_book_csv,
)

FIXTURE = [
    {
        "serviceId": "svc-cut", "name": "Haircut",
        "categoryName": "Hair", "duration": 60, "gapTime": 10,
        "price": 50.0, "archived": False,
        "internetDescription": "A cut.",
        "unmappedSourceField": {"nested": ["keep", "me"]},
        "staffCategories": {"prices": [
            {"id": "Senior", "price": 70.0}]},
        "userPrices": [],
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


def _summary(out):
    line = [ln for ln in out.splitlines()
            if ln.startswith("IMPORT_SUMMARY ")][0]
    return json.loads(line[len("IMPORT_SUMMARY "):])


def _import(payload, salon="Test Salon", suffix=".json"):
    out = io.StringIO()
    call_command("import_price_book", _write(payload, suffix=suffix),
                 salon=salon, stdout=out)
    return _summary(out.getvalue())


class PriceBookPayloadImportTests(TestCase):
    def test_json_import_stores_verbatim_payload(self):
        _import(FIXTURE)
        service = Service.objects.get(external_id="svc-cut")
        self.assertEqual(service.payload, FIXTURE[0])

    def test_identical_rerun_counts_unchanged(self):
        _import(FIXTURE)
        summary = _import(FIXTURE)
        self.assertEqual(summary["services"], 0)
        self.assertEqual(summary["services_updated"], 0)
        self.assertEqual(summary["services_unchanged"], 1)
        self.assertEqual(
            Service.objects.get(external_id="svc-cut").payload,
            FIXTURE[0])

    def test_payload_only_change_counts_updated(self):
        _import(FIXTURE)
        changed = json.loads(json.dumps(FIXTURE))
        changed[0]["unmappedSourceField"] = {"nested": ["changed"]}
        summary = _import(changed)
        self.assertEqual(summary["services"], 0)
        self.assertEqual(summary["services_updated"], 1)
        self.assertEqual(summary["services_unchanged"], 0)
        self.assertEqual(Service.objects.count(), 1)
        self.assertEqual(
            Service.objects.get(external_id="svc-cut").payload, changed[0])

    def test_csv_payload_restored_as_is_never_rewrapped(self):
        # Hand-built export-shape CSV: the payload cell is the
        # service's own source record and must land verbatim --
        # not wrapped in, or replaced by, the CSV row itself.
        payload = {"serviceId": "svc-cut", "legacyNote": "from source"}
        buffer = io.StringIO()
        writer = csv.DictWriter(
            buffer, fieldnames=PRICE_BOOK_FIELDNAMES + ["payload"],
            lineterminator="\n")
        writer.writeheader()
        writer.writerow({
            "salon_id": 1, "category_id": 1, "category_name": "Hair",
            "service_id": 9, "service_name": "Haircut", "description": "",
            "external_id": "svc-cut", "service_minutes": 60,
            "processing_minutes": 10, "finishing_minutes": 0,
            "total_minutes": 70, "service_active": True,
            "staff_level_id": "", "staff_level_name": "",
            "service_price_id": "", "amount": "", "is_from": "",
            "price_active": "", "payload": json.dumps(payload),
        })
        _import(buffer.getvalue(), suffix=".csv")
        service = Service.objects.get(external_id="svc-cut")
        self.assertEqual(service.payload, payload)

    def test_csv_without_payload_column_imports_empty_payload(self):
        _import(FIXTURE)
        salon = Salon.objects.get(name="Test Salon")
        # Strip payloads so the exported CSV is the pre-TF-10 shape.
        Service.objects.update(payload={})
        summary = _import(export_price_book_csv(salon), suffix=".csv")
        self.assertEqual(summary["services_unchanged"], 1)
        self.assertEqual(
            Service.objects.get(external_id="svc-cut").payload, {})


class PriceBookPayloadExportTests(TestCase):
    def setUp(self):
        _import(FIXTURE)
        self.salon = Salon.objects.get(name="Test Salon")
        self.service = Service.objects.get(external_id="svc-cut")

    def test_export_includes_payload_when_non_empty(self):
        records = export_price_book(self.salon)
        self.assertTrue(records)
        for record in records:
            self.assertEqual(record["payload"], FIXTURE[0])
        csv_text = export_price_book_csv(self.salon)
        header = csv_text.splitlines()[0].split(",")
        self.assertEqual(header, PRICE_BOOK_FIELDNAMES + ["payload"])
        self.assertIn("unmappedSourceField", csv_text)

    def test_export_omits_payload_when_empty(self):
        Service.objects.update(payload={})
        records = export_price_book(self.salon)
        for record in records:
            self.assertNotIn("payload", record)
            self.assertEqual(
                sorted(record), sorted(PRICE_BOOK_FIELDNAMES))
        csv_text = export_price_book_csv(self.salon)
        self.assertEqual(csv_text.splitlines()[0],
                         ",".join(PRICE_BOOK_FIELDNAMES))

    def test_full_round_trip_preserves_payload(self):
        csv_text = export_price_book_csv(self.salon)
        _import(csv_text, salon="Copy Salon", suffix=".csv")
        copied = Service.objects.get(external_id="svc-cut")
        # The payload survived the round trip byte-for-byte as a
        # value: a re-wrap in the CSV row would have changed it.
        self.assertEqual(copied.payload, FIXTURE[0])
        self.assertEqual(Service.objects.count(), 1)
        # And a second round trip from the copy is stable too.
        copy_salon = Salon.objects.get(name="Copy Salon")
        _import(export_price_book_csv(copy_salon), salon="Copy Salon",
                suffix=".csv")
        self.assertEqual(
            Service.objects.get(external_id="svc-cut").payload, FIXTURE[0])
