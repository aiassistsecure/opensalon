import io
from decimal import Decimal

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from catalog.models import Product
from saloncore.models import Salon


class UpdateProductCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SH-001",
            barcode="012345678905", price=Decimal("24.00"))

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        kwargs.setdefault("salon_id", self.salon.pk)
        kwargs.setdefault("product_id", self.product.pk)
        call_command("update_product", stdout=out, **kwargs)
        return out.getvalue()

    def snapshot(self):
        self.product.refresh_from_db()
        p = self.product
        return (p.name, p.sku, p.barcode, p.price, p.active)

    def test_happy_path_updates_and_reports(self):
        text = self.run_cmd(name="Conditioner", price="26.50")
        self.assertEqual(
            self.snapshot(),
            ("Conditioner", "SH-001", "012345678905",
             Decimal("26.50"), True))
        self.assertIn(f"Updated product {self.product.pk}", text)
        self.assertIn("Conditioner", text)

    def test_flag_form_active_and_inactive(self):
        out = io.StringIO()
        call_command(
            "update_product", "--salon-id", str(self.salon.pk),
            "--product-id", str(self.product.pk), "--inactive",
            stdout=out)
        self.assertFalse(self.snapshot()[4])
        self.assertIn("active=False", out.getvalue())
        out = io.StringIO()
        call_command(
            "update_product", "--salon-id", str(self.salon.pk),
            "--product-id", str(self.product.pk), "--active",
            stdout=out)
        self.assertTrue(self.snapshot()[4])

    def test_dry_run_writes_nothing_and_previews(self):
        before = self.snapshot()
        text = self.run_cmd(
            name="New Name", price="30.00", dry_run=True)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("Dry run: would update product", text)
        self.assertIn("New Name", text)
        self.assertIn("no product written", text)

    def test_dry_run_invalid_and_duplicate_barcode_write_nothing(self):
        Product.objects.create(
            salon=self.salon, name="Other", barcode="999",
            price=Decimal("1.00"))
        before = self.snapshot()
        for kwargs in ({"name": "  "}, {"price": "abc"},
                       {"price": "-2.00"}, {"barcode": "999"}):
            with self.assertRaises(CommandError):
                self.run_cmd(dry_run=True, **kwargs)
        self.assertEqual(self.snapshot(), before)

    def test_no_fields_refused(self):
        before = self.snapshot()
        with self.assertRaises(CommandError):
            self.run_cmd()
        self.assertEqual(self.snapshot(), before)

    def test_unknown_salon_and_product_raise(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, name="X")
        other = Salon.objects.create(name="Other Salon")
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=other.pk, name="X")
        with self.assertRaises(CommandError):
            self.run_cmd(product_id=999999, name="X")
        self.assertEqual(self.snapshot()[0], "Shampoo")

    def test_duplicate_barcode_refused_real_run(self):
        Product.objects.create(
            salon=self.salon, name="Other", barcode="999",
            price=Decimal("1.00"))
        with self.assertRaises(CommandError):
            self.run_cmd(barcode="999")
        self.assertEqual(self.snapshot()[2], "012345678905")
