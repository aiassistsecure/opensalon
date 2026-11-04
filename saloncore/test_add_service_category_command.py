import io

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from saloncore.models import Salon, ServiceCategory


class AddServiceCategoryCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_service_category", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Haircuts", sort_order=6)
        (cat,) = ServiceCategory.objects.all()
        self.assertEqual(
            (cat.salon, cat.name, cat.sort_order, cat.active),
            (self.salon, "Haircuts", 6, True))
        self.assertIn(f"Created service category {cat.pk}", text)
        self.assertIn("Haircuts", text)

    def test_flag_form_with_inactive(self):
        out = io.StringIO()
        call_command(
            "add_service_category", "--salon-id", str(self.salon.pk),
            "--name", "Color", "--sort-order", "1",
            "--inactive", stdout=out)
        (cat,) = ServiceCategory.objects.all()
        self.assertEqual((cat.sort_order, cat.active), (1, False))
        self.assertIn("active=False", out.getvalue())

    def test_dry_run_writes_nothing_and_previews(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Haircuts",
            sort_order=6, dry_run=True)
        self.assertEqual(ServiceCategory.objects.count(), 0)
        self.assertIn("Dry run: would create service category", text)
        self.assertIn("Haircuts", text)
        self.assertIn("sort_order=6", text)
        self.assertIn("no service category written", text)

    def test_dry_run_invalid_writes_nothing(self):
        for kwargs in ({"name": "  "}, {"name": "H", "sort_order": -1}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, dry_run=True, **kwargs)
        self.assertEqual(ServiceCategory.objects.count(), 0)

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="Haircuts")
        self.assertEqual(ServiceCategory.objects.count(), 0)

    def test_blank_name_and_bad_sort_order_raise(self):
        for kwargs in ({"name": "  "}, {"name": "H", "sort_order": -5}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, **kwargs)
        self.assertEqual(ServiceCategory.objects.count(), 0)
