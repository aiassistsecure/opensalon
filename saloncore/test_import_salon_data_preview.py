"""import_salon_data --dry-run slice-1 preview (audit-140).

Slice 1 sections (salons, service_categories, services,
staff_levels, service_prices) gain a read-only import_preview:
would-create / would-update / would-unchanged / would-skip counts
mirroring the writer's identity rules. Every other section keeps
its shape report exactly, with no preview. Writer never entered.
"""
import io
import json
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.dry_run import build_dry_run_reports
from saloncore.management.commands.import_salon_data import (
    KNOWN_KEYS, SECTIONS)
from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel)
from saloncore.test_import_salon_data import _minimal_data

SLICE1 = ("salons", "service_categories", "services",
          "staff_levels", "service_prices")
# Slices 2-6 also carry a preview; shape checks below exclude
# every previewed section, not just slice 1.
PREVIEWED = SLICE1 + ("clients", "client_notes", "staff_members",
                      "staff_services", "appointments",
                      "appointment_notes", "products",
                      "roster_patterns", "shift_overrides",
                      "attendance_records", "breaks", "sales",
                      "sale_items", "sale_payments", "refunds",
                      "cashups", "receipts", "stock_movements",
                      "price_changes", "reminder_sends", "campaigns",
                      "campaign_sends", "staff_notifications")
MODELS = (Salon, ServiceCategory, Service, StaffLevel, ServicePrice)


class ImportSalonDataPreviewTests(TestCase):
    def write_data(self, data):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, fh)
        fh.close()
        return fh.name

    def run_dry(self, data):
        out = io.StringIO()
        call_command("import_salon_data", self.write_data(data),
                     dry_run=True, stdout=out)
        return json.loads(out.getvalue())

    def counts(self):
        return {m.__name__: m.objects.count() for m in MODELS}

    def store_matching(self):
        salon = Salon.objects.create(
            name="TF6 Salon", timezone="UTC", currency="USD")
        category = ServiceCategory.objects.create(
            salon=salon, name="Color", sort_order=1, active=True)
        level = StaffLevel.objects.create(
            salon=salon, name="Level 6", sort_order=6, active=True)
        service = Service.objects.create(
            category=category, external_id="svc-1",
            name="Single Process", description="",
            service_minutes=45, processing_minutes=0,
            finishing_minutes=0, active=True)
        ServicePrice.objects.create(
            service=service, staff_level=level,
            amount=Decimal("85.00"), is_from=True, active=True)
        return salon

    def test_preview_present_only_on_slice1_sections(self):
        data = _minimal_data()
        reports = self.run_dry(data)
        self.assertEqual(set(reports), set(SECTIONS))
        for section in PREVIEWED:
            self.assertIn("import_preview", reports[section], section)
        for section in set(SECTIONS) - set(PREVIEWED):
            self.assertNotIn("import_preview", reports[section], section)

    def test_other_sections_shape_report_byte_identical(self):
        data = _minimal_data()
        reports = self.run_dry(data)
        # Phase 1 normalises int ids to str (TF-6) before the shape
        # report is built; mirror that in the expected input.
        normalised = json.loads(json.dumps(data))
        for rows in normalised.values():
            for row in rows:
                for key, value in list(row.items()):
                    if (key == "id" or key.endswith("_id")) \
                            and isinstance(value, int):
                        row[key] = str(value)
        expected = build_dry_run_reports({
            s: (normalised.get(s, []), KNOWN_KEYS[s]) for s in SECTIONS})
        for section in set(SECTIONS) - set(PREVIEWED):
            self.assertEqual(reports[section], expected[section], section)
        for section in PREVIEWED:  # shape keys unchanged, preview added
            shape = {k: v for k, v in reports[section].items()
                     if k != "import_preview"}
            self.assertEqual(shape, expected[section], section)

    def test_would_create_all_slice1_on_empty_db(self):
        reports = self.run_dry(_minimal_data())
        for section in SLICE1:
            preview = reports[section]["import_preview"]
            self.assertEqual(
                (preview["total"], preview["would_create"],
                 preview["would_update"], preview["would_unchanged"],
                 preview["would_skip"]), (1, 1, 0, 0, 0), section)
            self.assertEqual(preview["skipped_rows"], [], section)

    def test_would_unchanged_against_matching_stored(self):
        self.store_matching()
        reports = self.run_dry(_minimal_data())
        for section in SLICE1:
            preview = reports[section]["import_preview"]
            self.assertEqual(preview["would_unchanged"], 1, section)
            self.assertEqual(preview["would_create"], 0, section)

    def test_would_update_when_stored_fields_differ(self):
        self.store_matching()
        data = _minimal_data()
        data["service_prices"][0]["amount"] = "90.00"
        data["salons"][0]["tagline"] = "New tagline"
        reports = self.run_dry(data)
        self.assertEqual(
            reports["service_prices"]["import_preview"]["would_update"], 1)
        self.assertEqual(
            reports["salons"]["import_preview"]["would_update"], 1)
        self.assertEqual(
            reports["services"]["import_preview"]["would_unchanged"], 1)

    def test_repeat_row_in_file_judged_against_first_row(self):
        data = _minimal_data()
        data["salons"].append(dict(data["salons"][0]))
        data["services"].append(
            dict(data["services"][0], name="Renamed Process"))
        reports = self.run_dry(data)
        salon = reports["salons"]["import_preview"]
        self.assertEqual(
            (salon["would_create"], salon["would_unchanged"]), (1, 1))
        svc = reports["services"]["import_preview"]
        self.assertEqual(
            (svc["would_create"], svc["would_update"]), (1, 1))

    def test_new_child_of_file_created_parent_would_create(self):
        # Parent salon/category/level/service exist only in the
        # file: the price row is still a would-create, not a skip.
        reports = self.run_dry(_minimal_data())
        price = reports["service_prices"]["import_preview"]
        self.assertEqual(price["would_skip"], 0)
        self.assertEqual(price["skipped_rows"], [])

    def test_dry_run_writes_nothing_explicit(self):
        self.store_matching()
        before = self.counts()
        data = _minimal_data()
        data["salons"][0]["tagline"] = "Changed"  # would-update
        data["services"].append(dict(
            data["services"][0], id=21, external_id="svc-2",
            name="Brand New"))  # would-create
        self.run_dry(data)
        self.assertEqual(self.counts(), before)
        self.assertEqual(Salon.objects.get().tagline, "")
        self.assertFalse(Service.objects.filter(
            external_id="svc-2").exists())

    def test_phase1_validation_still_fails_closed_on_dry_run(self):
        data = _minimal_data()
        data["services"][0]["active"] = "false"  # TF-3 strict bool
        with self.assertRaises(CommandError):
            self.run_dry(data)
        self.assertTrue(all(c == 0 for c in self.counts().values()))
