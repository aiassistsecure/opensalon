"""import_price_book --dry-run preview counts (audit-138 tail).

The dry path keeps the per-file shape reports verbatim and adds
read-only ``import_preview`` counts to the services report:
would-create / would-update / would-unchanged / would-refuse per
service plan (service fields plus the prices it would set), judged
by the writer's own identity + phase-1 validation helpers against
a simulated state seeded from stored services. The writer is
never entered and NOTHING is written — asserted explicitly,
including a stored price staying at its old amount.
"""
import io
import json
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from saloncore.models import (
    PriceChange, Salon, Service, ServiceCategory, ServicePrice,
    StaffLevel,
)

FIXTURE = [
    {
        "serviceId": "svc-1", "name": "Haircut", "categoryName": "Hair",
        "duration": 60, "gapTime": 0, "price": 50.0, "archived": False,
        "internetDescription": "A cut.",
        "staffCategories": {"prices": [{"id": "lvl-senior", "price": 70.0}]},
        "userPrices": [],
    },
]
STAFF = [
    {"staffId": "p-1", "userId": "p-1", "staffCategoryId": "lvl-senior",
     "staffCategoryName": "Senior"},
]
CSV_TEXT = (
    "service_name,category_name,description,external_id,"
    "service_minutes,processing_minutes,finishing_minutes,"
    "service_active,staff_level_name,amount,is_from,price_active\n"
    "Haircut,Hair,A cut.,svc-c1,60,0,0,true,Base,50,false,true\n")


def _write(payload, suffix=".json"):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8")
    if suffix == ".json":
        json.dump(payload, fh)
    else:
        fh.write(payload)
    fh.close()
    return fh.name


class ImportPriceBookPreviewTests(TestCase):
    def _dry(self, payload=FIXTURE, **kwargs):
        out = io.StringIO()
        path = _write(payload)
        call_command("import_price_book", path, dry_run=True,
                     stdout=out, **kwargs)
        return json.loads(out.getvalue())[path], path

    def _real(self, payload=FIXTURE, **kwargs):
        out = io.StringIO()
        call_command("import_price_book", _write(payload),
                     stdout=out, **kwargs)

    def test_shape_report_kept_verbatim_alongside_preview(self):
        report, _ = self._dry()
        self.assertEqual(report["record_count"], 1)
        self.assertIn("price", report["fields"])
        preview = report["import_preview"]
        self.assertEqual(preview["salon"], "My Salon")
        self.assertFalse(preview["salon_found"])
        self.assertEqual(preview["total"], 1)
        self.assertEqual(preview["would_create"], 1)
        self.assertFalse(Salon.objects.exists())

    def test_would_unchanged_after_real_import(self):
        self._real()
        preview = self._dry()[0]["import_preview"]
        self.assertTrue(preview["salon_found"])
        self.assertEqual(preview["would_unchanged"], 1)
        self.assertEqual(preview["would_create"], 0)
        self.assertEqual(preview["would_update"], 0)

    def test_would_update_on_price_change_and_field_change(self):
        self._real()
        changed_price = [dict(FIXTURE[0], price=55.0)]
        preview = self._dry(payload=changed_price)[0]["import_preview"]
        self.assertEqual(preview["would_update"], 1)
        changed_field = [dict(FIXTURE[0], duration=90)]
        preview = self._dry(payload=changed_field)[0]["import_preview"]
        self.assertEqual(preview["would_update"], 1)

    def test_would_refuse_for_skipped_and_invalid_rows(self):
        rows = FIXTURE + [
            {"categoryName": "Hair"},                 # no name: skipped
            {"name": "Bad", "duration": "abc"},       # phase-1 refusal
            {"name": "Bad2", "archived": "junk"},     # phase-1 refusal
        ]
        preview = self._dry(payload=rows)[0]["import_preview"]
        self.assertEqual(preview["total"], 4)
        self.assertEqual(preview["would_create"], 1)
        self.assertEqual(preview["would_refuse"], 3)

    def test_repeat_row_in_file_judged_against_first_row(self):
        same = self._dry(payload=FIXTURE + FIXTURE)[0]["import_preview"]
        self.assertEqual(same["would_create"], 1)
        self.assertEqual(same["would_unchanged"], 1)
        diff = self._dry(payload=FIXTURE + [dict(FIXTURE[0], price=60.0)]
                         )[0]["import_preview"]
        self.assertEqual(diff["would_create"], 1)
        self.assertEqual(diff["would_update"], 1)

    def test_staff_file_resolves_level_names_in_preview(self):
        staff_path = _write(STAFF)
        self._real(staff=staff_path)
        out = io.StringIO()
        path = _write(FIXTURE)
        call_command("import_price_book", path, dry_run=True,
                     staff=staff_path, stdout=out)
        reports = json.loads(out.getvalue())
        self.assertIn(staff_path, reports)
        preview = reports[path]["import_preview"]
        self.assertEqual(preview["would_unchanged"], 1)

    def test_csv_preview_counts_create_then_unchanged(self):
        path = _write(CSV_TEXT, suffix=".csv")
        out = io.StringIO()
        call_command("import_price_book", path, dry_run=True, stdout=out)
        preview = json.loads(out.getvalue())[path]["import_preview"]
        self.assertEqual(preview["would_create"], 1)
        out = io.StringIO()
        call_command("import_price_book", path, stdout=out)
        out = io.StringIO()
        call_command("import_price_book", path, dry_run=True, stdout=out)
        preview = json.loads(out.getvalue())[path]["import_preview"]
        self.assertEqual(preview["would_unchanged"], 1)

    def test_dry_run_writes_nothing_and_stored_price_unchanged(self):
        self._real()
        stored = ServicePrice.objects.get(
            service__external_id="svc-1",
            staff_level__name="Base")
        before = (
            Salon.objects.count(), Service.objects.count(),
            ServiceCategory.objects.count(), StaffLevel.objects.count(),
            ServicePrice.objects.count(), PriceChange.objects.count(),
            stored.amount)
        rows = [
            dict(FIXTURE[0], price=99.0),                    # would-update
            dict(FIXTURE[0], serviceId="svc-new", name="New Cut"),
            {"categoryName": "Hair"},                        # would-refuse
        ]
        preview = self._dry(payload=rows)[0]["import_preview"]
        self.assertEqual(preview["would_update"], 1)
        self.assertEqual(preview["would_create"], 1)
        self.assertEqual(preview["would_refuse"], 1)
        stored.refresh_from_db()
        after = (
            Salon.objects.count(), Service.objects.count(),
            ServiceCategory.objects.count(), StaffLevel.objects.count(),
            ServicePrice.objects.count(), PriceChange.objects.count(),
            stored.amount)
        self.assertEqual(before, after)
        self.assertEqual(stored.amount, Decimal("50.00"))
        self.assertFalse(
            Service.objects.filter(external_id="svc-new").exists())
