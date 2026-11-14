import io
import json
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.models import Product
from saloncore.models import Salon


class AddProductCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_product", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path_creates_product(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Shampoo", price="24.00",
            sku="SH-001", barcode="012345678905")
        (p,) = Product.objects.all()
        self.assertEqual(
            (p.name, p.sku, p.barcode, p.price, p.active),
            ("Shampoo", "SH-001", "012345678905",
             Decimal("24.00"), True))
        self.assertIn(f"Created product {p.pk}", text)
        self.assertIn("Shampoo", text)

    def test_flag_form_with_inactive(self):
        out = io.StringIO()
        call_command(
            "add_product", "--salon-id", str(self.salon.pk),
            "--name", "Old Stock", "--price", "5.00", "--inactive",
            stdout=out)
        (p,) = Product.objects.all()
        self.assertFalse(p.active)
        self.assertIn("active=False", out.getvalue())

    def test_dry_run_writes_nothing_and_previews(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Shampoo", price="24.00",
            sku="SH-001", barcode="012345678905", dry_run=True)
        self.assertEqual(Product.objects.count(), 0)
        self.assertIn("Dry run: would create product", text)
        self.assertIn("Shampoo", text)
        self.assertIn("012345678905", text)
        self.assertIn("24.00", text)
        self.assertIn("no product written", text)

    def test_dry_run_invalid_writes_nothing_before_equals_after(self):
        Product.objects.create(
            salon=self.salon, name="Existing",
            barcode="999", price=Decimal("10.00"))
        before = Product.objects.count()
        for kwargs in ({"name": "  ", "price": "1.00"},
                       {"name": "X", "price": "abc"},
                       {"name": "X", "price": "-2.00"}):
            with self.assertRaises(CommandError):
                self.run_cmd(
                    salon_id=self.salon.pk, dry_run=True, **kwargs)
        self.assertEqual(Product.objects.count(), before)

    def test_dry_run_duplicate_barcode_refused_writes_nothing(self):
        Product.objects.create(
            salon=self.salon, name="Existing",
            barcode="012345678905", price=Decimal("10.00"))
        with self.assertRaises(CommandError):
            self.run_cmd(
                salon_id=self.salon.pk, name="Copy", price="10.00",
                barcode="012345678905", dry_run=True)
        self.assertEqual(Product.objects.count(), 1)

    def test_duplicate_barcode_refused(self):
        self.run_cmd(salon_id=self.salon.pk, name="Shampoo",
                     price="24.00", barcode="012345678905")
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk, name="Copy",
                         price="24.00", barcode="012345678905")
        self.assertEqual(Product.objects.count(), 1)

    def test_same_barcode_other_salon_allowed(self):
        other = Salon.objects.create(name="Other Salon")
        self.run_cmd(salon_id=self.salon.pk, name="A", price="1.00",
                     barcode="012345678905")
        self.run_cmd(salon_id=other.pk, name="B", price="1.00",
                     barcode="012345678905")
        self.assertEqual(Product.objects.count(), 2)

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="X", price="1.00")
        self.assertEqual(Product.objects.count(), 0)

    def test_default_text_output_unchanged(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Shampoo", price="24.00",
            sku="SH-001", barcode="012345678905")
        (p,) = Product.objects.all()
        self.assertEqual(
            text,
            f"Created product {p.pk}: 'Shampoo' "
            f"in salon {self.salon.pk}: sku='SH-001' "
            f"barcode='012345678905' price=24.00 active=True.\n")

    def test_explicit_text_format_matches_default(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Shampoo", price="24.00",
            format="text")
        self.assertIn("Created product", text)
        self.assertNotIn("{", text)

    def test_format_json_parses_and_carries_expected_fields(self):
        out = io.StringIO()
        call_command(
            "add_product", "--salon-id", str(self.salon.pk),
            "--name", "Shampoo", "--price", "24.00",
            "--sku", "SH-001", "--barcode", "012345678905",
            "--format", "json", stdout=out)
        text = out.getvalue()
        self.assertEqual(len(text.strip().splitlines()), 1)
        data = json.loads(text)
        (p,) = Product.objects.all()
        self.assertEqual(data["product_id"], p.pk)
        self.assertEqual(data["salon_id"], self.salon.pk)
        self.assertEqual(data["name"], "Shampoo")
        self.assertEqual(data["sku"], "SH-001")
        self.assertEqual(data["barcode"], "012345678905")
        self.assertEqual(data["price"], "24.00")
        self.assertIs(data["active"], True)
        self.assertIs(data["dry_run"], False)

    def test_dry_run_format_json_reports_dry_run_and_writes_nothing(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Shampoo", price="24.00",
            sku="SH-001", barcode="012345678905", dry_run=True,
            format="json")
        data = json.loads(text)
        self.assertIsNone(data["product_id"])
        self.assertEqual(data["salon_id"], self.salon.pk)
        self.assertEqual(data["name"], "Shampoo")
        self.assertEqual(data["sku"], "SH-001")
        self.assertEqual(data["barcode"], "012345678905")
        self.assertEqual(data["price"], "24.00")
        self.assertIs(data["active"], True)
        self.assertIs(data["dry_run"], True)
        self.assertEqual(Product.objects.count(), 0)

    def test_dry_run_text_output_unchanged_with_format_text(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, name="Shampoo", price="24.00",
            dry_run=True, format="text")
        self.assertIn("Dry run: would create product", text)
        self.assertEqual(Product.objects.count(), 0)

    def test_format_json_errors_still_raise_command_error(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="X", price="1.00",
                         format="json")
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk, name="X",
                         price="-2.00", format="json")
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=self.salon.pk, name="X",
                         price="-2.00", dry_run=True, format="json")
        self.assertEqual(Product.objects.count(), 0)

    def test_blank_name_and_bad_price_raise(self):
        for kwargs in ({"name": "  ", "price": "1.00"},
                       {"name": "X", "price": "abc"},
                       {"name": "X", "price": "-2.00"}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, **kwargs)
        self.assertEqual(Product.objects.count(), 0)
