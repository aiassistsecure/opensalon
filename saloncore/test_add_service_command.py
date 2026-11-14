import io
import json

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory


class AddServiceCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_service", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path_by_category_id(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, category_id=self.category.pk,
            name="Full Color", service_minutes=60,
            description="All-over", processing_minutes=30,
            finishing_minutes=15)
        (s,) = Service.objects.all()
        self.assertEqual(
            (s.category, s.name, s.description, s.service_minutes,
             s.processing_minutes, s.finishing_minutes, s.active),
            (self.category, "Full Color", "All-over", 60, 30, 15, True))
        self.assertIn(f"Created service {s.pk}", text)
        self.assertIn("Full Color", text)

    def test_flag_form_with_inactive_and_category_name(self):
        out = io.StringIO()
        call_command(
            "add_service", "--salon-id", str(self.salon.pk),
            "--category-name", "Color", "--name", "Old",
            "--service-minutes", "30", "--inactive", stdout=out)
        (s,) = Service.objects.all()
        self.assertFalse(s.active)
        self.assertIn("active=False", out.getvalue())

    def test_dry_run_by_name_writes_nothing_and_previews(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, category_name="Color",
            name="Full Color", service_minutes=60,
            processing_minutes=30, dry_run=True)
        self.assertEqual(Service.objects.count(), 0)
        self.assertIn("Dry run: would create service", text)
        self.assertIn("Full Color", text)
        self.assertIn("Color", text)
        self.assertIn("service_minutes=60", text)
        self.assertIn("no service written", text)

    def test_dry_run_invalid_writes_nothing(self):
        before = Service.objects.count()
        for kwargs in ({"name": "  ", "service_minutes": 45,
                        "category_id": self.category.pk},
                       {"name": "Cut", "service_minutes": 0,
                        "category_id": self.category.pk},
                       {"name": "Cut", "service_minutes": 45,
                        "category_name": "Missing"},
                       {"name": "Cut", "service_minutes": 45}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, dry_run=True, **kwargs)
        self.assertEqual(Service.objects.count(), before)

    def test_both_category_forms_refused(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk,
                         category_id=self.category.pk,
                         category_name="Color", name="Cut",
                         service_minutes=45)
        self.assertEqual(Service.objects.count(), 0)

    def test_cross_salon_category_id_refused(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = ServiceCategory.objects.create(salon=other, name="Color")
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk, category_id=foreign.pk,
                         name="Cut", service_minutes=45)
        self.assertEqual(Service.objects.count(), 0)

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, category_id=self.category.pk,
                         name="Cut", service_minutes=45)
        self.assertEqual(Service.objects.count(), 0)

    def test_blank_name_and_bad_minutes_raise(self):
        for kwargs in ({"name": "  ", "service_minutes": 45},
                       {"name": "Cut", "service_minutes": -1},
                       {"name": "Cut", "service_minutes": 45,
                        "processing_minutes": -5}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk,
                             category_id=self.category.pk, **kwargs)
        self.assertEqual(Service.objects.count(), 0)


class AddServiceCommandFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_service", stdout=out, **kwargs)
        return out.getvalue()

    def test_default_text_output_unchanged(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, category_id=self.category.pk,
            name="Full Color", service_minutes=60,
            processing_minutes=30, finishing_minutes=15)
        (s,) = Service.objects.all()
        self.assertEqual(
            text,
            f"Created service {s.pk}: 'Full Color' "
            f"in salon {self.salon.pk}: category={self.category.pk} "
            "service_minutes=60 processing_minutes=30 "
            "finishing_minutes=15 active=True.\n")

    def test_default_text_dry_run_output_unchanged(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, category_id=self.category.pk,
            name="Full Color", service_minutes=60,
            processing_minutes=30, dry_run=True)
        self.assertEqual(
            text,
            "Dry run: would create service 'Full Color' "
            f"in salon {self.salon.pk}: category={self.category.pk} "
            "('Color') service_minutes=60 processing_minutes=30 "
            "finishing_minutes=0 active=True "
            "-- no service written.\n")
        self.assertEqual(Service.objects.count(), 0)

    def test_explicit_text_format_matches_default(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, category_id=self.category.pk,
            name="Full Color", service_minutes=60, format="text")
        (s,) = Service.objects.all()
        self.assertEqual(
            text,
            f"Created service {s.pk}: 'Full Color' "
            f"in salon {self.salon.pk}: category={self.category.pk} "
            "service_minutes=60 processing_minutes=0 "
            "finishing_minutes=0 active=True.\n")

    def test_json_output_parses_and_carries_facts(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, category_id=self.category.pk,
            name="Full Color", service_minutes=60,
            processing_minutes=30, finishing_minutes=15,
            format="json")
        (s,) = Service.objects.all()
        self.assertNotIn("Created service", text)
        self.assertEqual(json.loads(text), {
            "id": s.pk, "name": "Full Color",
            "salon_id": self.salon.pk,
            "category_id": self.category.pk,
            "category_name": "Color",
            "service_minutes": 60, "processing_minutes": 30,
            "finishing_minutes": 15, "active": True,
            "dry_run": False})

    def test_json_via_cli_flag(self):
        out = io.StringIO()
        call_command(
            "add_service", "--salon-id", str(self.salon.pk),
            "--category-id", str(self.category.pk),
            "--name", "Full Color", "--service-minutes", "60",
            "--format", "json", stdout=out)
        row = json.loads(out.getvalue())
        (s,) = Service.objects.all()
        self.assertEqual(
            (row["id"], row["name"], row["salon_id"],
             row["category_id"], row["dry_run"]),
            (s.pk, "Full Color", self.salon.pk,
             self.category.pk, False))

    def test_dry_run_json_reports_dry_run_and_writes_nothing(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, category_name="Color",
            name="Full Color", service_minutes=60,
            processing_minutes=30, dry_run=True, format="json")
        self.assertEqual(Service.objects.count(), 0)
        self.assertNotIn("Dry run", text)
        self.assertEqual(json.loads(text), {
            "id": None, "name": "Full Color",
            "salon_id": self.salon.pk,
            "category_id": self.category.pk,
            "category_name": "Color",
            "service_minutes": 60, "processing_minutes": 30,
            "finishing_minutes": 0, "active": True,
            "dry_run": True})

    def test_json_invalid_writes_nothing_and_raises_command_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(
                salon_id=self.salon.pk,
                category_id=self.category.pk, name="Cut",
                service_minutes=0, format="json")
        self.assertEqual(Service.objects.count(), 0)
