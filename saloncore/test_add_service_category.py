from django.test import TestCase

from saloncore.add_service_category import (
    add_service_category,
    validate_add_service_category,
)
from saloncore.models import Salon, ServiceCategory


class AddServiceCategoryTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def test_creates_with_all_fields(self):
        cat = add_service_category(
            self.salon, "  Haircuts  ", sort_order=6, active=False)
        self.assertEqual(ServiceCategory.objects.count(), 1)
        self.assertEqual(
            (cat.salon, cat.name, cat.sort_order, cat.active),
            (self.salon, "Haircuts", 6, False))

    def test_defaults_sort_order_zero_active_true(self):
        cat = add_service_category(self.salon, "Color")
        self.assertEqual((cat.sort_order, cat.active), (0, True))

    def test_scoped_to_given_salon_and_duplicates_allowed(self):
        a = add_service_category(self.salon, "Haircuts")
        b = add_service_category(self.other, "Haircuts")
        c = add_service_category(self.salon, "Haircuts")
        self.assertEqual((a.salon, b.salon), (self.salon, self.other))
        self.assertEqual(ServiceCategory.objects.count(), 3)
        self.assertNotEqual(a.pk, c.pk)

    def test_string_sort_order_accepted(self):
        cat = add_service_category(self.salon, "Color", sort_order="2")
        self.assertEqual(cat.sort_order, 2)

    def test_blank_or_overlong_name_refused(self):
        for bad in ("", "   ", None, 123, "x" * 121):
            with self.assertRaises(ValueError):
                add_service_category(self.salon, bad)
        self.assertEqual(ServiceCategory.objects.count(), 0)

    def test_bad_sort_order_and_active_refused(self):
        for kwargs in ({"sort_order": -1}, {"sort_order": "abc"},
                       {"sort_order": 1.5}, {"sort_order": True},
                       {"sort_order": None}, {"active": "yes"},
                       {"active": 1}):
            with self.assertRaises(ValueError):
                add_service_category(self.salon, "Haircuts", **kwargs)
        self.assertEqual(ServiceCategory.objects.count(), 0)

    def test_unsaved_salon_refused(self):
        with self.assertRaises(ValueError):
            add_service_category(Salon(name="Unsaved"), "Haircuts")
        self.assertEqual(ServiceCategory.objects.count(), 0)

    def test_validate_writes_nothing(self):
        cleaned = validate_add_service_category(
            self.salon, "  Color  ", sort_order="3", active=False)
        self.assertEqual(ServiceCategory.objects.count(), 0)
        self.assertEqual(
            (cleaned["salon"], cleaned["name"],
             cleaned["sort_order"], cleaned["active"]),
            (self.salon, "Color", 3, False))

    def test_validate_rejects_invalid_writing_nothing(self):
        for kwargs in ({"name": " "}, {"name": "C", "sort_order": -2}):
            with self.assertRaises(ValueError):
                validate_add_service_category(self.salon, **kwargs)
        self.assertEqual(ServiceCategory.objects.count(), 0)


import io
import json

from django.core.management import call_command
from django.core.management.base import CommandError


class AddServiceCategoryCommandFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_service_category", stdout=out, **kwargs)
        return out.getvalue()

    def test_default_text_output_unchanged(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Haircuts", sort_order=6)
        (cat,) = ServiceCategory.objects.all()
        self.assertEqual(
            text,
            f"Created service category {cat.pk}: 'Haircuts' "
            f"in salon {self.salon.pk}: sort_order=6 active=True.\n")

    def test_explicit_text_format_matches_default(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Haircuts", sort_order=6,
            format="text")
        (cat,) = ServiceCategory.objects.all()
        self.assertEqual(
            text,
            f"Created service category {cat.pk}: 'Haircuts' "
            f"in salon {self.salon.pk}: sort_order=6 active=True.\n")

    def test_json_output_parses_and_carries_facts(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Haircuts", sort_order=6,
            format="json")
        (cat,) = ServiceCategory.objects.all()
        self.assertNotIn("Created service category", text)
        self.assertEqual(json.loads(text), {
            "id": cat.pk, "name": "Haircuts",
            "salon_id": self.salon.pk, "sort_order": 6,
            "active": True, "dry_run": False})

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "add_service_category", "--salon-id", str(self.salon.pk),
            "--name", "Color", "--sort-order", "1",
            "--inactive", "--format", "json", stdout=out)
        row = json.loads(out.getvalue())
        (cat,) = ServiceCategory.objects.all()
        self.assertEqual(
            (row["id"], row["name"], row["salon_id"],
             row["sort_order"], row["active"], row["dry_run"]),
            (cat.pk, "Color", self.salon.pk, 1, False, False))

    def test_dry_run_text_default_unchanged(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Haircuts", sort_order=6,
            dry_run=True)
        self.assertEqual(
            text,
            "Dry run: would create service category 'Haircuts' "
            f"in salon {self.salon.pk}: sort_order=6 active=True "
            "-- no service category written.\n")
        self.assertEqual(ServiceCategory.objects.count(), 0)

    def test_dry_run_json_reports_dry_run_and_writes_nothing(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Haircuts", sort_order=6,
            dry_run=True, format="json")
        self.assertEqual(ServiceCategory.objects.count(), 0)
        self.assertNotIn("Dry run", text)
        self.assertEqual(json.loads(text), {
            "id": None, "name": "Haircuts",
            "salon_id": self.salon.pk, "sort_order": 6,
            "active": True, "dry_run": True})

    def test_json_invalid_writes_nothing_and_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd(
                salon_id=self.salon.pk, name="  ", format="json")
        self.assertEqual(ServiceCategory.objects.count(), 0)
