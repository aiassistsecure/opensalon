import io

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
