"""TF-12 dry-run tests for import_price_book: JSON report, zero writes."""
import io
import json
import tempfile

from django.core.management import call_command
from django.test import TestCase

from saloncore.models import Service, ServicePrice, StaffLevel

FIXTURE = [
    {
        "serviceId": "svc-1", "name": "Haircut", "categoryName": "Hair",
        "duration": 60, "gapTime": 0, "price": 50.0, "archived": False,
        "internetDescription": "A cut.",
        "staffCategories": {"prices": [{"id": "lvl-senior", "price": 70.0}]},
        "userPrices": [],
        "legacyVendorCode": "LV-1",
    },
]

STAFF = [
    {"staffId": "p-1", "userId": "p-1", "staffCategoryId": "lvl-senior",
     "staffCategoryName": "Senior", "legacyStaffCode": "LS-1"},
]


def _write(payload, suffix=".json"):
    fh = tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, delete=False, encoding="utf-8")
    if suffix == ".json":
        json.dump(payload, fh)
    else:
        fh.write(payload)
    fh.close()
    return fh.name


def _reports(out):
    return json.loads(out)


class ImportPriceBookDryRunTests(TestCase):
    def run_dry(self, payload=FIXTURE, **kwargs):
        out = io.StringIO()
        path = _write(payload)
        call_command("import_price_book", path, dry_run=True,
                     stdout=out, **kwargs)
        return out.getvalue(), path

    def test_dry_run_writes_zero_rows_and_names_unmapped_key(self):
        out, path = self.run_dry()
        self.assertEqual(Service.objects.count(), 0)
        self.assertEqual(StaffLevel.objects.count(), 0)
        self.assertEqual(ServicePrice.objects.count(), 0)
        report = _reports(out)[path]
        self.assertEqual(report["record_count"], 1)
        self.assertIn("legacyVendorCode", report["unmapped_keys"])

    def test_dry_run_null_missing_empty_string_are_distinct(self):
        rows = [
            {"name": "A", "internetDescription": None},
            {"name": "B"},
            {"name": "C"},
            {"name": "D", "internetDescription": ""},
            {"name": "E", "internetDescription": ""},
            {"name": "F", "internetDescription": ""},
            {"name": "G", "internetDescription": "A cut."},
        ]
        out, path = self.run_dry(payload=rows)
        field = _reports(out)[path]["fields"]["internetDescription"]
        self.assertEqual(field["null"], 1)
        self.assertEqual(field["missing"], 2)
        self.assertEqual(field["empty_string"], 3)
        self.assertEqual(field["valued"], 1)

    def test_dry_run_with_staff_reports_both_files_writes_nothing(self):
        staff_path = _write(STAFF)
        out, path = self.run_dry(staff=staff_path)
        reports = _reports(out)
        self.assertIn("legacyStaffCode",
                      reports[staff_path]["unmapped_keys"])
        self.assertIn(path, reports)
        self.assertEqual(Service.objects.count(), 0)
        self.assertEqual(StaffLevel.objects.count(), 0)
        self.assertEqual(ServicePrice.objects.count(), 0)

    def test_dry_run_csv_writes_nothing_and_names_unmapped_key(self):
        csv_text = (
            "service_name,category_name,amount,legacy_code\n"
            "Haircut,Hair,50.0,LV-1\n")
        path = _write(csv_text, suffix=".csv")
        out = io.StringIO()
        call_command("import_price_book", path, dry_run=True, stdout=out)
        report = _reports(out.getvalue())[path]
        self.assertIn("legacy_code", report["unmapped_keys"])
        self.assertEqual(Service.objects.count(), 0)
        self.assertEqual(StaffLevel.objects.count(), 0)
        self.assertEqual(ServicePrice.objects.count(), 0)

    def test_normal_import_of_same_fixture_still_works(self):
        out = io.StringIO()
        call_command("import_price_book", _write(FIXTURE), stdout=out)
        self.assertIn("IMPORT_SUMMARY", out.getvalue())
        self.assertEqual(Service.objects.count(), 1)
        self.assertEqual(StaffLevel.objects.count(), 2)
        self.assertEqual(ServicePrice.objects.count(), 2)
