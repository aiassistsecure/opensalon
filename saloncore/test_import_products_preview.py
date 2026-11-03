"""import_products --dry-run preview twin (audit-138 rank 4).

The dry path keeps the pure shape report verbatim and adds a
read-only import preview: per-record would-create / would-update /
would-unchanged / would-skip counts keyed on the writer's own
identity rule (salon + external_id), barcode/SKU collisions —
within the file and against stored products — named by row, and
price validation previewed as missing_price skips. The writer is
never entered and NOTHING is written.
"""
import json
import tempfile
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from catalog.models import Product, StockMovement
from saloncore.models import Salon


def _row(**overrides):
    row = {
        "productId": "p-1", "name": "Aveda Shampoo", "code": "11511",
        "barcode": "018084000001", "price": 38.0, "reorderCost": 19.5,
        "brandName": "Aveda", "categoryName": "Hair Care",
        "type": "RETAIL", "archived": False, "quantityInStock": 6,
    }
    row.update(overrides)
    return row


class ImportProductsPreviewTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Test Salon")

    def _dry(self, records, salon="Test Salon"):
        fh = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False)
        json.dump(records, fh)
        fh.close()
        out = StringIO()
        call_command("import_products", fh.name, "--salon", salon,
                     "--dry-run", stdout=out)
        return json.loads(out.getvalue())

    def _stored(self, **overrides):
        fields = {
            "salon": self.salon, "external_id": "p-1",
            "name": "Aveda Shampoo", "sku": "11511",
            "barcode": "018084000001", "price": Decimal("38.00"),
            "active": True, "brand_name": "Aveda",
            "category_name": "Hair Care", "product_type": "RETAIL",
            "cost_price": Decimal("19.50"), "payload": _row(),
        }
        fields.update(overrides)
        return Product.objects.create(**fields)

    def test_shape_report_kept_verbatim_alongside_preview(self):
        report = self._dry([_row(**{"parentProductId": "parent-9"})])
        self.assertEqual(report["record_count"], 1)
        self.assertIn("parentProductId", report["unmapped_keys"])
        self.assertIn("price", report["fields"])
        preview = report["import_preview"]
        self.assertEqual(preview["salon"], "Test Salon")
        self.assertTrue(preview["salon_found"])
        self.assertEqual(preview["total"], 1)

    def test_would_create_and_stock_preview_for_new_products(self):
        preview = self._dry([
            _row(),
            _row(productId="p-2", name="Colour Tube", code="",
                 barcode="", quantityInStock=0),
        ])["import_preview"]
        self.assertEqual(preview["would_create"], 2)
        self.assertEqual(preview["would_update"], 0)
        self.assertEqual(preview["would_skip"], 0)
        self.assertEqual(preview["would_open_stock_movements"], 1)

    def test_would_update_and_would_unchanged_against_stored(self):
        self._stored()
        preview = self._dry([
            _row(),  # identical to the stored product
            _row(productId="p-2", name="Other", price=38.0),
        ])["import_preview"]
        self.assertEqual(preview["would_unchanged"], 1)
        self.assertEqual(preview["would_create"], 1)
        changed = self._dry([_row(price=40.0)])["import_preview"]
        self.assertEqual(changed["would_update"], 1)
        self.assertEqual(changed["would_unchanged"], 0)

    def test_repeat_product_id_in_file_judged_against_first_row(self):
        # The writer creates on row 0, then row 1 meets that new
        # product: identical fields = unchanged, differing = update.
        same = self._dry([_row(), _row()])["import_preview"]
        self.assertEqual(same["would_create"], 1)
        self.assertEqual(same["would_unchanged"], 1)
        diff = self._dry(
            [_row(), _row(price=41.0)])["import_preview"]
        self.assertEqual(diff["would_create"], 1)
        self.assertEqual(diff["would_update"], 1)

    def test_price_validation_previewed_and_named_by_row(self):
        preview = self._dry([
            _row(),
            {"productId": "p-np", "name": "No Price"},
            _row(productId="p-bad", price="abc"),
        ])["import_preview"]
        self.assertEqual(preview["would_create"], 1)
        self.assertEqual(preview["would_skip"], 2)
        self.assertEqual(preview["skipped_missing_price"], 2)
        self.assertEqual(
            preview["skipped_rows"],
            [{"row": 1, "reason": "missing_price"},
             {"row": 2, "reason": "missing_price"}])

    def test_other_writer_skips_previewed_with_reasons(self):
        preview = self._dry([
            _row(productId="x" * 65),
            _row(productId="p-long-code", code="y" * 65),
            {"name": "No Id", "price": 1.0},
            _row(productId="p-frac", quantityInStock=2.9),
        ])["import_preview"]
        self.assertEqual(preview["would_skip"], 4)
        self.assertEqual(preview["skipped_id_too_long"], 2)
        self.assertEqual(
            [r["reason"] for r in preview["skipped_rows"]],
            ["id_too_long", "id_too_long", "missing_id_or_name",
             "invalid_record"])

    def test_barcode_collision_within_file_named_by_row(self):
        preview = self._dry([
            _row(),
            _row(productId="p-2", name="Copycat", code="99999"),
        ])["import_preview"]
        self.assertEqual(preview["barcode_collisions"], [
            {"row": 1, "code": "018084000001", "in_file_row": 0}])
        self.assertEqual(preview["sku_collisions"], [])

    def test_barcode_and_sku_collision_against_stored_named(self):
        self._stored()
        preview = self._dry([
            _row(productId="p-9", name="Squatter"),
        ])["import_preview"]
        self.assertEqual(preview["barcode_collisions"], [
            {"row": 0, "code": "018084000001",
             "stored_external_id": "p-1"}])
        self.assertEqual(preview["sku_collisions"], [
            {"row": 0, "code": "11511", "stored_external_id": "p-1"}])
        # The squatter row itself still counts as a would-create:
        # the writer has no collision refusal — the preview's job
        # is to name it before commit, not to change the writer.
        self.assertEqual(preview["would_create"], 1)

    def test_own_product_reclaiming_its_codes_is_no_collision(self):
        self._stored()
        preview = self._dry([_row(price=40.0)])["import_preview"]
        self.assertEqual(preview["barcode_collisions"], [])
        self.assertEqual(preview["sku_collisions"], [])
        self.assertEqual(preview["would_update"], 1)

    def test_blank_codes_never_collide(self):
        preview = self._dry([
            _row(code="", barcode=""),
            _row(productId="p-2", name="Also Blank", code="",
                 barcode=""),
        ])["import_preview"]
        self.assertEqual(preview["barcode_collisions"], [])
        self.assertEqual(preview["sku_collisions"], [])

    def test_unknown_salon_previews_all_creates_and_creates_none(self):
        preview = self._dry([_row()], salon="Ghost Salon")[
            "import_preview"]
        self.assertFalse(preview["salon_found"])
        self.assertEqual(preview["would_create"], 1)
        self.assertFalse(Salon.objects.filter(name="Ghost Salon"))

    def test_dry_run_writes_nothing_explicit(self):
        stored = self._stored()
        before = (
            Salon.objects.count(), Product.objects.count(),
            StockMovement.objects.count(),
            Product.objects.get(pk=stored.pk).price,
            Product.objects.get(pk=stored.pk).payload,
        )
        self._dry([
            _row(price=99.0),                       # would-update
            _row(productId="p-new", name="New"),    # would-create
            {"productId": "p-np", "name": "No Price"},  # would-skip
        ])
        after = (
            Salon.objects.count(), Product.objects.count(),
            StockMovement.objects.count(),
            Product.objects.get(pk=stored.pk).price,
            Product.objects.get(pk=stored.pk).payload,
        )
        self.assertEqual(before, after)
        self.assertFalse(
            Product.objects.filter(external_id="p-new").exists())
        self.assertFalse(
            Product.objects.filter(external_id="p-np").exists())
