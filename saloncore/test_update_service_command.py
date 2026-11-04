import io

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.add_service import add_service
from saloncore.models import Salon, Service, ServiceCategory


class UpdateServiceCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.cuts = ServiceCategory.objects.create(
            salon=self.salon, name="Cuts")
        self.service = add_service(
            self.salon, "Full Color", 60, category=self.category,
            description="All-over", processing_minutes=30,
            finishing_minutes=15)

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("service_id", self.service.pk)
        call_command("update_service", stdout=out, **kwargs)
        return out.getvalue()

    def stored(self):
        return Service.objects.get(pk=self.service.pk)

    def test_happy_path_partial_by_category_id(self):
        text = self.run_cmd(category_id=self.cuts.pk, name="Balayage",
                            service_minutes=90)
        stored = self.stored()
        self.assertEqual(
            (stored.category, stored.name, stored.description,
             stored.service_minutes, stored.processing_minutes,
             stored.active),
            (self.cuts, "Balayage", "All-over", 90, 30, True))
        self.assertIn(f"Updated service {self.service.pk}", text)
        self.assertIn("Balayage", text)

    def test_flag_form_inactive_and_category_name(self):
        out = io.StringIO()
        call_command(
            "update_service", "--salon-id", str(self.salon.pk),
            "--service-id", str(self.service.pk),
            "--category-name", "Cuts", "--inactive", stdout=out)
        stored = self.stored()
        self.assertEqual((stored.category, stored.active), (self.cuts, False))
        self.assertIn("active=False", out.getvalue())

    def test_flag_form_active_reactivates(self):
        self.service.active = False
        self.service.save()
        out = io.StringIO()
        call_command(
            "update_service", "--salon-id", str(self.salon.pk),
            "--service-id", str(self.service.pk), "--active", stdout=out)
        self.assertTrue(self.stored().active)

    def test_both_active_and_inactive_refused(self):
        out = io.StringIO()
        with self.assertRaises(CommandError):
            call_command(
                "update_service", "--salon-id", str(self.salon.pk),
                "--service-id", str(self.service.pk),
                "--active", "--inactive", stdout=out)
        self.assertTrue(self.stored().active)

    def test_dry_run_writes_nothing_and_previews(self):
        text = self.run_cmd(name="Balayage", service_minutes=90,
                            category_name="Cuts", dry_run=True)
        stored = self.stored()
        self.assertEqual(
            (stored.name, stored.service_minutes, stored.category),
            ("Full Color", 60, self.category))
        self.assertIn("Dry run: would update service", text)
        self.assertIn("name='Balayage'", text)
        self.assertIn("service_minutes=90", text)
        self.assertIn("no service written", text)

    def test_dry_run_invalid_and_no_field_write_nothing(self):
        for kwargs in ({"name": "  "}, {"service_minutes": 0},
                       {"category_name": "Missing"}, {}):
            with self.assertRaises(CommandError):
                self.run_cmd(dry_run=True, **kwargs)
        self.assertEqual(self.stored().name, "Full Color")

    def test_no_field_given_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd()
        self.assertEqual(self.stored().name, "Full Color")

    def test_both_category_forms_and_cross_salon_refused(self):
        other = Salon.objects.create(name="Other Salon")
        foreign_cat = ServiceCategory.objects.create(salon=other, name="X")
        foreign = add_service(other, "Cut", 45, category=foreign_cat)
        for kwargs in ({"category_id": self.cuts.pk,
                        "category_name": "Cuts"},
                       {"category_id": foreign_cat.pk}):
            with self.assertRaises(CommandError):
                self.run_cmd(**kwargs)
        with self.assertRaises(CommandError):
            self.run_cmd(service_id=foreign.pk, name="X")
        self.assertEqual(self.stored().category, self.category)

    def test_unknown_salon_or_service_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="X")
        with self.assertRaises(CommandError):
            self.run_cmd(service_id=999999, name="X")

    def test_blank_name_and_bad_minutes_raise(self):
        for kwargs in ({"name": "  "}, {"service_minutes": -1},
                       {"processing_minutes": -5}):
            with self.assertRaises(CommandError):
                self.run_cmd(**kwargs)
        self.assertEqual(self.stored().name, "Full Color")
