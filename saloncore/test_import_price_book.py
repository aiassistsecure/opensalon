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
    Salon,
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

    def test_external_id_populated_from_service_id(self):
        self.run_import()
        self.assertEqual(
            Service.objects.get(name="Haircut").external_id, "svc-1")
        self.assertEqual(
            Service.objects.get(name="Old Perm").external_id, "svc-2")

    def test_external_id_populated_from_generic_id_field(self):
        payload = [{"id": "ext-9", "name": "Trim", "categoryName": "Hair",
                    "duration": 30, "price": 25.0}]
        self.run_import(payload=payload)
        self.assertEqual(
            Service.objects.get(name="Trim").external_id, "ext-9")

    def test_rerun_with_external_id_is_idempotent(self):
        self.run_import()
        self.run_import()
        self.assertEqual(Service.objects.count(), 2)
        self.assertEqual(
            Service.objects.get(name="Haircut").external_id, "svc-1")

    def test_rerun_renamed_service_with_same_id_updates_in_place(self):
        self.run_import()
        changed = json.loads(json.dumps(FIXTURE))
        changed[0]["name"] = "Haircut Deluxe"
        self.run_import(payload=changed)
        self.assertEqual(Service.objects.count(), 2)
        self.assertEqual(
            Service.objects.get(external_id="svc-1").name, "Haircut Deluxe")

    def test_row_without_id_gains_external_id_on_reimport(self):
        no_ids = json.loads(json.dumps(FIXTURE))
        for row in no_ids:
            row.pop("serviceId", None)
        self.run_import(payload=no_ids)
        self.assertEqual(Service.objects.get(name="Haircut").external_id, "")
        self.run_import()
        self.assertEqual(Service.objects.count(), 2)
        self.assertEqual(
            Service.objects.get(name="Haircut").external_id, "svc-1")

    def test_rerun_without_id_does_not_clobber_external_id(self):
        self.run_import()
        no_ids = json.loads(json.dumps(FIXTURE))
        for row in no_ids:
            row.pop("serviceId", None)
        self.run_import(payload=no_ids)
        self.assertEqual(Service.objects.count(), 2)
        self.assertEqual(
            Service.objects.get(name="Haircut").external_id, "svc-1")

    def test_record_without_id_still_imports(self):
        payload = [{"name": "Trim", "categoryName": "Hair",
                    "duration": 30, "price": 25.0}]
        self.run_import(payload=payload)
        trim = Service.objects.get(name="Trim")
        self.assertEqual(trim.external_id, "")
        self.assertEqual(ServicePrice.objects.count(), 1)

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


class ImportPriceBookStrictArchivedTests(TestCase):
    """TF-2: JSON ``archived`` parses strictly, never by truthiness
    (string "false" is truthy, so the old ``not row.get(...)``
    inactivated live services)."""

    def run_import(self, payload):
        out = io.StringIO()
        call_command("import_price_book", _write(payload),
                     stdout=out)
        return out.getvalue()

    def row(self, **overrides):
        row = {
            "serviceId": "svc-x", "name": "Cut", "categoryName": "Hair",
            "duration": 30, "price": 25.0,
            "staffCategories": {"prices": []}, "userPrices": [],
        }
        row.update(overrides)
        return row

    def test_archived_string_false_imports_active(self):
        self.run_import([self.row(archived="false")])
        self.assertTrue(Service.objects.get(name="Cut").active)

    def test_archived_string_true_imports_inactive(self):
        self.run_import([self.row(archived="true")])
        self.assertFalse(Service.objects.get(name="Cut").active)

    def test_archived_string_variants(self):
        cases = [
            ("False", True), ("TRUE", False), ("0", True),
            ("1", False), ("no", True), ("yes", False),
            (0, True), (1, False),
        ]
        payload = [
            self.row(serviceId=f"svc-{i}", name=f"Svc {i}",
                     archived=value)
            for i, (value, _expected) in enumerate(cases)
        ]
        self.run_import(payload)
        for i, (_value, expected) in enumerate(cases):
            self.assertEqual(
                Service.objects.get(name=f"Svc {i}").active, expected)

    def test_archived_missing_imports_active(self):
        self.run_import([self.row()])
        self.assertTrue(Service.objects.get(name="Cut").active)

    def test_archived_junk_raises_and_writes_nothing(self):
        for junk in ("maybe", "", None, 2):
            with self.subTest(junk=junk):
                with self.assertRaises(CommandError):
                    self.run_import([self.row(archived=junk)])
                self.assertEqual(Service.objects.count(), 0)


class ImportPriceBookPreValidationTests(TestCase):
    """N-M20a validate-before-write: a bad row anywhere in the file
    raises CommandError in phase 1 and writes zero rows on any
    backend (on NEDB atomic() rolls back nothing — DYOR §9.4)."""

    MODELS = (Salon, ServiceCategory, Service, StaffLevel,
              ServicePrice, PriceChange)

    def assert_zero_rows(self):
        for model in self.MODELS:
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def assert_bad_file_writes_nothing(self, payload):
        with self.assertRaises(CommandError):
            call_command("import_price_book", _write(payload),
                         stdout=io.StringIO())
        self.assert_zero_rows()

    def good_row(self, **overrides):
        row = {
            "serviceId": "svc-good", "name": "Good Cut",
            "categoryName": "Hair", "duration": 45, "gapTime": 0,
            "price": 40.0, "archived": False,
            "staffCategories": {"prices": [
                {"id": "lvl-senior", "price": 55.0}]},
            "userPrices": [],
        }
        row.update(overrides)
        return row

    def test_bad_duration_mid_file_writes_nothing(self):
        payload = [
            self.good_row(),
            self.good_row(serviceId="svc-bad", name="Bad Cut",
                          duration="not-a-number"),
            self.good_row(serviceId="svc-later", name="Later Cut"),
        ]
        self.assert_bad_file_writes_nothing(payload)

    def test_bad_gap_time_mid_file_writes_nothing(self):
        payload = [
            self.good_row(),
            self.good_row(serviceId="svc-bad", name="Bad Cut",
                          gapTime="soon"),
        ]
        self.assert_bad_file_writes_nothing(payload)

    def test_non_dict_staff_categories_writes_nothing(self):
        payload = [
            self.good_row(),
            self.good_row(serviceId="svc-bad", name="Bad Cut",
                          staffCategories=["not", "an", "object"]),
        ]
        self.assert_bad_file_writes_nothing(payload)

    def test_non_dict_prices_entry_writes_nothing(self):
        payload = [
            self.good_row(),
            self.good_row(
                serviceId="svc-bad", name="Bad Cut",
                staffCategories={"prices": ["not-an-object"]}),
        ]
        self.assert_bad_file_writes_nothing(payload)

    def test_unparseable_level_price_writes_nothing(self):
        payload = [
            self.good_row(),
            self.good_row(
                serviceId="svc-bad", name="Bad Cut",
                staffCategories={"prices": [
                    {"id": "lvl-senior", "price": "free-ish"}]}),
        ]
        self.assert_bad_file_writes_nothing(payload)

    def test_valid_file_regression_imports_unchanged(self):
        out = io.StringIO()
        call_command("import_price_book", _write(FIXTURE), stdout=out)
        self.assertIn("IMPORT_SUMMARY", out.getvalue())
        self.assertEqual(ServiceCategory.objects.count(), 1)
        self.assertEqual(Service.objects.count(), 2)
        self.assertEqual(StaffLevel.objects.count(), 3)
        self.assertEqual(ServicePrice.objects.count(), 4)
        cut = Service.objects.get(name="Haircut")
        self.assertEqual(cut.service_minutes, 60)
        self.assertEqual(
            ServicePrice.objects.get(
                service=cut, staff_level__name="Base").amount,
            Decimal("50.0"))
