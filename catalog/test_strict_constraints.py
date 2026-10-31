"""N-M-next: StrictConstraints enforces catalog Meta.constraints.

Product carries the conditional UniqueConstraint
``uniq_product_external_id`` (unique when external_id > "").
On schemaless NEDB no database-level constraint exists, so the
app-layer guard (saloncore.StrictConstraints, DYOR §9.3) is the
only enforcement — the census-53 genuine failure was this test's
saloncore counterpart passing on SQLite (DB-enforced) while the
duplicate was silently accepted on NEDB.
"""
from decimal import Decimal

from django.apps import apps
from django.db import IntegrityError, transaction
from django.test import TestCase

from catalog.models import Product
from saloncore.models import Salon, StrictConstraints


class ProductStrictConstraintsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Test Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Aveda Shampoo",
            external_id="p-1", price=Decimal("38.00"),
        )

    def test_duplicate_nonempty_external_id_rejected_on_save(self):
        dupe = Product(
            salon=self.salon, name="Dupe",
            external_id="p-1", price=Decimal("1.00"),
        )
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                dupe.save()
        self.assertEqual(Product.objects.count(), 1)

    def test_duplicate_nonempty_external_id_rejected_on_create(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Product.objects.create(
                    salon=self.salon, name="Dupe",
                    external_id="p-1", price=Decimal("1.00"),
                )
        self.assertEqual(Product.objects.count(), 1)

    def test_update_into_duplicate_external_id_rejected(self):
        other = Product.objects.create(
            salon=self.salon, name="Other",
            external_id="p-2", price=Decimal("2.00"),
        )
        other.external_id = "p-1"
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                other.save()

    def test_multiple_blank_external_id_allowed(self):
        Product.objects.create(
            salon=self.salon, name="No Id One", price=Decimal("1.00"),
        )
        Product.objects.create(
            salon=self.salon, name="No Id Two", price=Decimal("2.00"),
        )
        self.assertEqual(
            Product.objects.filter(external_id="").count(), 2
        )

    def test_bulk_create_duplicate_rejected_and_blank_batch_allowed(self):
        with self.assertRaises(IntegrityError):
            Product.objects.bulk_create([
                Product(salon=self.salon, name="Bulk Dupe",
                        external_id="p-1", price=Decimal("1.00")),
            ])
        Product.objects.bulk_create([
            Product(salon=self.salon, name="Bulk Blank One",
                    price=Decimal("1.00")),
            Product(salon=self.salon, name="Bulk Blank Two",
                    price=Decimal("2.00")),
        ])
        self.assertEqual(
            Product.objects.filter(external_id="").count(), 2
        )


class ConstrainedModelsUseStrictConstraintsTests(TestCase):
    """Generic guard: every model declaring Meta.constraints must
    inherit StrictConstraints, or its constraints are unenforced
    on NEDB. This is what makes the fix generic, not Product-only.
    """

    def test_all_constrained_models_inherit_strict_constraints(self):
        offenders = [
            model._meta.label
            for model in apps.get_models()
            if model._meta.constraints
            and not issubclass(model, StrictConstraints)
        ]
        self.assertEqual(offenders, [])
