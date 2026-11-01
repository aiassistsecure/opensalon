"""Tests for the shared importer dry-run helper (TF-12).

Synthetic data only. ``SimpleTestCase`` forbids database queries, so
a green run also proves the helper performs zero database writes.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from django.test import SimpleTestCase

from saloncore.dry_run import (
    build_dry_run_report,
    build_dry_run_reports,
    infer_value_type,
)


class InferValueTypeTests(SimpleTestCase):
    def test_scalar_types(self):
        self.assertEqual(infer_value_type(True), "bool")
        self.assertEqual(infer_value_type(7), "int")
        self.assertEqual(infer_value_type(1.5), "float")
        self.assertEqual(infer_value_type("hello"), "string")
        self.assertEqual(infer_value_type(None), "null")
        self.assertEqual(infer_value_type(""), "empty_string")
        self.assertEqual(infer_value_type([1]), "list")
        self.assertEqual(infer_value_type({"a": 1}), "dict")

    def test_bool_is_not_int(self):
        # bool subclasses int; inference must check bool first.
        self.assertNotEqual(infer_value_type(False), "int")

    def test_decimal_is_never_float(self):
        self.assertEqual(infer_value_type(Decimal("12.50")), "decimal")

    def test_date_and_datetime(self):
        self.assertEqual(infer_value_type(date(2026, 10, 3)), "date")
        aware = datetime(2026, 10, 3, 9, 0, tzinfo=timezone.utc)
        self.assertEqual(infer_value_type(aware), "datetime")

    def test_strings_are_not_coerced(self):
        cases = {
            "42": "integer_string",
            "-7": "integer_string",
            "12.50": "decimal_string",
            "true": "bool_string",
            "False": "bool_string",
            "2026-10-03": "date_string",
            "2026-10-03T09:00:00+00:00": "datetime_string",
            "2026-13-40": "string",  # date-shaped but invalid
            "abc-123": "string",
        }
        for raw, expected in cases.items():
            self.assertEqual(infer_value_type(raw), expected, raw)


class DryRunReportTests(SimpleTestCase):
    def test_empty_input_no_records(self):
        report = build_dry_run_report([], {"name", "price"})
        self.assertEqual(report["record_count"], 0)
        self.assertEqual(report["unmapped_keys"], [])
        self.assertEqual(report["mapped_keys"], ["name", "price"])
        for key in ("name", "price"):
            field = report["fields"][key]
            self.assertEqual(field["inferred_type"], "unknown")
            self.assertEqual(field["types"], {})
            self.assertEqual(field["present"], 0)
            self.assertEqual(field["missing"], 0)
            self.assertEqual(field["null"], 0)
            self.assertEqual(field["empty_string"], 0)

    def test_empty_input_no_mapped_keys(self):
        report = build_dry_run_report([], set())
        self.assertEqual(report["fields"], {})
        self.assertEqual(report["record_count"], 0)

    def test_type_inference_per_key(self):
        records = [
            {"name": "Cut", "price": Decimal("50.00"), "mins": 30},
            {"name": "Color", "price": Decimal("85.00"), "mins": 60},
        ]
        report = build_dry_run_report(records, {"name", "price", "mins"})
        self.assertEqual(report["fields"]["name"]["inferred_type"], "string")
        self.assertEqual(report["fields"]["price"]["inferred_type"], "decimal")
        self.assertEqual(report["fields"]["mins"]["inferred_type"], "int")
        self.assertEqual(report["fields"]["mins"]["types"], {"int": 2})

    def test_mixed_types_reported_as_mixed(self):
        records = [{"v": 1}, {"v": "one"}]
        field = build_dry_run_report(records, {"v"})["fields"]["v"]
        self.assertEqual(field["inferred_type"], "mixed")
        self.assertEqual(field["types"], {"int": 1, "string": 1})

    def test_null_missing_empty_are_distinct(self):
        records = [
            {"email": "a@example.com"},
            {"email": None},
            {"email": ""},
            {"name": "No email key at all"},
        ]
        field = build_dry_run_report(records, {"email"})["fields"]["email"]
        self.assertEqual(field["present"], 3)
        self.assertEqual(field["null"], 1)
        self.assertEqual(field["empty_string"], 1)
        self.assertEqual(field["missing"], 1)
        self.assertEqual(field["valued"], 1)
        # Absences never pollute type inference.
        self.assertEqual(field["types"], {"string": 1})
        self.assertEqual(field["inferred_type"], "string")

    def test_counts_always_sum_to_record_count(self):
        records = [{"a": 1, "b": None}, {"a": ""}, {}]
        report = build_dry_run_report(records, {"a", "b"})
        for field in report["fields"].values():
            self.assertEqual(field["present"] + field["missing"], 3)
            valued = field["present"] - field["null"] - field["empty_string"]
            self.assertEqual(field["valued"], valued)

    def test_mapped_key_absent_everywhere(self):
        report = build_dry_run_report([{"a": 1}], {"a", "ghost"})
        ghost = report["fields"]["ghost"]
        self.assertEqual(ghost["missing"], 1)
        self.assertEqual(ghost["present"], 0)
        self.assertEqual(ghost["inferred_type"], "unknown")

    def test_unmapped_keys_detected_sorted(self):
        records = [{"name": "Cut", "legacyCode": "X1", "zzExtra": 1}]
        report = build_dry_run_report(records, {"name"})
        self.assertEqual(report["unmapped_keys"], ["legacyCode", "zzExtra"])
        # Unmapped keys still get full field stats.
        self.assertEqual(
            report["fields"]["legacyCode"]["inferred_type"], "string"
        )

    def test_no_unmapped_when_all_keys_mapped(self):
        report = build_dry_run_report([{"a": 1, "b": 2}], {"a", "b"})
        self.assertEqual(report["unmapped_keys"], [])

    def test_source_name_carried_through(self):
        report = build_dry_run_report([], set(), source_name="2026-10.json")
        self.assertEqual(report["source"], "2026-10.json")
        self.assertIsNone(build_dry_run_report([], set())["source"])

    def test_inputs_are_not_mutated(self):
        records = [{"a": 1}, {"a": None}]
        mapped = {"a"}
        build_dry_run_report(records, mapped)
        self.assertEqual(records, [{"a": 1}, {"a": None}])
        self.assertEqual(mapped, {"a"})

    def test_non_dict_record_rejected(self):
        with self.assertRaises(TypeError):
            build_dry_run_report([{"a": 1}, ["not", "a", "dict"]], {"a"})


class DryRunReportsTests(SimpleTestCase):
    def test_per_file_reports_tuple_and_dict_specs(self):
        reports = build_dry_run_reports({
            "clients.json": ([{"id": "1", "extra": True}], {"id"}),
            "empty.json": {"records": [], "mapped_keys": {"id"}},
        })
        self.assertEqual(list(reports), ["clients.json", "empty.json"])
        self.assertEqual(reports["clients.json"]["source"], "clients.json")
        self.assertEqual(reports["clients.json"]["unmapped_keys"], ["extra"])
        self.assertEqual(
            reports["clients.json"]["fields"]["extra"]["inferred_type"],
            "bool",
        )
        self.assertEqual(reports["empty.json"]["record_count"], 0)
