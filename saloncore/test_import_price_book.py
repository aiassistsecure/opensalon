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


class ImportPriceBookExternalIdLengthTests(TestCase):
    """TF-6: ids are never silently truncated; staff-file ids are
    normalised to str. This importer is validate-before-write, so an
    overlong id raises CommandError naming the row in phase 1 and
    the whole file writes nothing (zero partial write for that row).
    Mirrors the clients/bookings TF-6 pattern (never truncate an
    identity) in this command's own error mechanism."""

    AT_LIMIT = "x" * 64
    OVER_LIMIT = "x" * 65
    LEVEL_AT_LIMIT = "L" * 120
    LEVEL_OVER_LIMIT = "L" * 121

    MODELS = (Salon, ServiceCategory, Service, StaffLevel,
              ServicePrice, PriceChange)

    def run_import(self, payload=FIXTURE, **kwargs):
        out = io.StringIO()
        call_command("import_price_book", _write(payload),
                     stdout=out, **kwargs)
        return out.getvalue()

    def assert_zero_rows(self):
        for model in self.MODELS:
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def row(self, **overrides):
        row = {
            "serviceId": "svc-x", "name": "Cut", "categoryName": "Hair",
            "duration": 30, "price": 25.0,
            "staffCategories": {"prices": []}, "userPrices": [],
        }
        row.update(overrides)
        return row

    def test_overlong_service_id_raises_naming_row_writes_nothing(self):
        payload = [self.row(),
                   self.row(serviceId=self.OVER_LIMIT, name="Bad Cut")]
        with self.assertRaises(CommandError) as caught:
            self.run_import(payload)
        self.assertIn("Row 1", str(caught.exception))
        self.assertIn("serviceId", str(caught.exception))
        self.assert_zero_rows()
        # No silently truncated identity was stored.
        self.assertFalse(
            Service.objects.filter(external_id=self.AT_LIMIT).exists())

    def test_overlong_fallback_id_raises_naming_row(self):
        row = self.row()
        del row["serviceId"]
        row["id"] = self.OVER_LIMIT
        with self.assertRaises(CommandError) as caught:
            self.run_import([row])
        self.assertIn("Row 0", str(caught.exception))
        self.assert_zero_rows()

    def test_two_overlong_ids_sharing_prefix_do_not_collide(self):
        prefix = "b" * 64
        payload = [self.row(serviceId=prefix + "1", name="One"),
                   self.row(serviceId=prefix + "2", name="Two")]
        with self.assertRaises(CommandError):
            self.run_import(payload)
        self.assert_zero_rows()

    def test_overlong_csv_external_id_raises_naming_row(self):
        header = ("salon_id,category_id,category_name,service_id,"
                  "service_name,description,external_id,service_minutes,"
                  "processing_minutes,finishing_minutes,total_minutes,"
                  "service_active,staff_level_id,staff_level_name,"
                  "service_price_id,amount,is_from,price_active")
        csv_row = (f",,Hair,,Cut,,{self.OVER_LIMIT},30,0,0,30,"
                   "true,,,25.0,,")
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8")
        fh.write(header + "\n" + csv_row + "\n")
        fh.close()
        with self.assertRaises(CommandError) as caught:
            call_command("import_price_book", fh.name,
                         stdout=io.StringIO())
        self.assertIn("Row 0", str(caught.exception))
        self.assert_zero_rows()

    def test_at_limit_service_id_imports_exactly(self):
        self.run_import([self.row(serviceId=self.AT_LIMIT)])
        self.assertEqual(
            Service.objects.get(name="Cut").external_id, self.AT_LIMIT)

    def test_normal_ids_import_identically(self):
        out = self.run_import()
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertEqual(Service.objects.count(), 2)
        self.assertEqual(StaffLevel.objects.count(), 3)
        self.assertEqual(ServicePrice.objects.count(), 4)
        self.assertEqual(
            Service.objects.get(name="Haircut").external_id, "svc-1")

    def test_overlong_level_id_raises_naming_row_writes_nothing(self):
        row = self.row(staffCategories={"prices": [
            {"id": self.LEVEL_OVER_LIMIT, "price": 10.0}]})
        with self.assertRaises(CommandError) as caught:
            self.run_import([row])
        self.assertIn("Row 0", str(caught.exception))
        self.assert_zero_rows()
        self.assertFalse(StaffLevel.objects.filter(
            name=self.LEVEL_AT_LIMIT).exists())

    def test_at_limit_level_id_imports_as_level_name(self):
        row = self.row(staffCategories={"prices": [
            {"id": self.LEVEL_AT_LIMIT, "price": 10.0}]})
        self.run_import([row])
        self.assertTrue(StaffLevel.objects.filter(
            name=self.LEVEL_AT_LIMIT).exists())

    def test_numeric_service_id_normalised_to_str(self):
        self.run_import([self.row(serviceId=12345)])
        cut = Service.objects.get(name="Cut")
        self.assertEqual(cut.external_id, "12345")
        self.assertIsInstance(cut.external_id, str)

    def test_staff_file_numeric_category_id_matches_string_price_id(self):
        staff = [{"staffId": 201, "userId": 201,
                  "staffCategoryId": 101,
                  "staffCategoryName": "Senior"}]
        row = self.row(staffCategories={"prices": [
            {"id": "101", "price": 70.0}]})
        self.run_import([row], staff=_write(staff))
        self.assertEqual(
            set(StaffLevel.objects.values_list("name", flat=True)),
            {"Base", "Senior"})

    def test_staff_file_string_category_id_matches_numeric_price_id(self):
        staff = [{"staffId": "201", "userId": "201",
                  "staffCategoryId": "101",
                  "staffCategoryName": "Senior"}]
        row = self.row(staffCategories={"prices": [
            {"id": 101, "price": 70.0}]})
        self.run_import([row], staff=_write(staff))
        self.assertEqual(
            set(StaffLevel.objects.values_list("name", flat=True)),
            {"Base", "Senior"})

    def test_staff_file_numeric_user_id_still_skips_individual(self):
        staff = [{"staffId": 201, "userId": 201,
                  "staffCategoryId": 101,
                  "staffCategoryName": "Senior"}]
        row = self.row(staffCategories={"prices": [
            {"id": "201", "price": 70.0}]})
        out = self.run_import([row], staff=_write(staff))
        summary = json.loads(
            [ln for ln in out.splitlines()
             if ln.startswith("IMPORT_SUMMARY ")][0][len("IMPORT_SUMMARY "):])
        self.assertEqual(summary["skipped_individual_prices"], 1)
        self.assertEqual(StaffLevel.objects.count(), 1)  # Base only.
