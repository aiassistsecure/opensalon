import io
import json

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.add_service_category import add_service_category
from saloncore.models import Salon, ServiceCategory


class UpdateServiceCategoryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.category = add_service_category(
            self.salon, "Haircuts", sort_order=6, active=True)

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("service_category_id", self.category.pk)
        call_command("update_service_category", stdout=out, **kwargs)
        return out.getvalue()

    def stored(self):
        return ServiceCategory.objects.get(pk=self.category.pk)

    def test_happy_path_partial(self):
        text = self.run_cmd(name="Hair", sort_order=8)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Hair", 8, True))
        self.assertIn(f"Updated service category {self.category.pk}", text)
        self.assertIn("Hair", text)

    def test_flag_form_inactive(self):
        out = io.StringIO()
        call_command(
            "update_service_category", "--salon-id", str(self.salon.pk),
            "--service-category-id", str(self.category.pk),
            "--inactive", stdout=out)
        self.assertFalse(self.stored().active)
        self.assertIn("active=False", out.getvalue())

    def test_flag_form_active_reactivates(self):
        self.category.active = False
        self.category.save()
        out = io.StringIO()
        call_command(
            "update_service_category", "--salon-id", str(self.salon.pk),
            "--service-category-id", str(self.category.pk),
            "--active", stdout=out)
        self.assertTrue(self.stored().active)

    def test_both_active_and_inactive_refused(self):
        out = io.StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "update_service_category", "--salon-id", str(self.salon.pk),
                "--service-category-id", str(self.category.pk),
                "--active", "--inactive", stdout=out)
        self.assertTrue(self.stored().active)

    def test_dry_run_writes_nothing_and_previews(self):
        text = self.run_cmd(name="Hair", sort_order=8, dry_run=True)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Haircuts", 6, True))
        self.assertIn("Dry run: would update service category", text)
        self.assertIn("name='Hair'", text)
        self.assertIn("sort_order=8", text)
        self.assertIn("no service category written", text)

    def test_dry_run_invalid_and_no_field_write_nothing(self):
        for kwargs in ({"name": "  "}, {"sort_order": -1}, {}):
            with self.assertRaises(CommandError):
                self.run_cmd(dry_run=True, **kwargs)
        self.assertEqual(self.stored().name, "Haircuts")

    def test_no_field_given_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd()
        self.assertEqual(self.stored().name, "Haircuts")

    def test_cross_salon_category_refused(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = add_service_category(other, "Color")
        with self.assertRaises(CommandError):
            self.run_cmd(service_category_id=foreign.pk, name="X")
        self.assertEqual(self.stored().name, "Haircuts")

    def test_unknown_salon_or_category_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="X")
        with self.assertRaises(CommandError):
            self.run_cmd(service_category_id=999999, name="X")

    def test_blank_name_and_bad_sort_order_raise(self):
        for kwargs in ({"name": "  "}, {"sort_order": -5}):
            with self.assertRaises(CommandError):
                self.run_cmd(**kwargs)
        self.assertEqual(self.stored().name, "Haircuts")

    def test_explicit_text_format_matches_default(self):
        text = self.run_cmd(name="Hair", sort_order=8, format="text")
        self.assertEqual(
            text,
            f"Updated service category {self.category.pk}: 'Hair' "
            f"in salon {self.salon.pk}: sort_order=8 active=True.\n")
        self.assertEqual(self.stored().name, "Hair")

    def test_json_output_parses_and_carries_facts(self):
        text = self.run_cmd(name="Hair", sort_order=8, format="json")
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Hair", 8, True))
        self.assertNotIn("Updated service category", text)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertEqual(json.loads(text), {
            "id": self.category.pk, "name": "Hair",
            "salon_id": self.salon.pk, "sort_order": 8,
            "active": True, "dry_run": False})

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "update_service_category", "--salon-id", str(self.salon.pk),
            "--service-category-id", str(self.category.pk),
            "--inactive", "--format", "json", stdout=out)
        row = json.loads(out.getvalue())
        self.assertEqual(
            (row["id"], row["salon_id"], row["active"],
             row["dry_run"]),
            (self.category.pk, self.salon.pk, False, False))
        self.assertFalse(self.stored().active)

    def test_dry_run_json_reports_dry_run_and_writes_nothing(self):
        text = self.run_cmd(
            name="Hair", sort_order=8, dry_run=True, format="json")
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.sort_order, stored.active),
            ("Haircuts", 6, True))
        self.assertNotIn("Dry run", text)
        self.assertEqual(json.loads(text), {
            "id": self.category.pk, "salon_id": self.salon.pk,
            "name": "Hair", "sort_order": 8, "dry_run": True})

    def test_json_errors_still_command_error(self):
        for kwargs in ({"name": "  "}, {"sort_order": -5}, {}):
            with self.assertRaises(CommandError):
                self.run_cmd(format="json", **kwargs)
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="X", format="json")
        with self.assertRaises(CommandError):
            self.run_cmd(name="X", dry_run=True, format="bogus")
        self.assertEqual(self.stored().name, "Haircuts")
