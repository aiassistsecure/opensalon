"""N-M18: StrictConstraints guard for bulk_create()/bulk_update()/update().

The bulk paths bypass save(), so without the guard they also bypassed
the declared Meta.constraints catalog (NEDB DYOR §9.3/§9.4). Every
rejection surface here is IntegrityError, matching save() and a
database-level constraint, and a rejected batch writes nothing.
"""
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import F
from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory, ServicePrice, StaffLevel


class BulkGuardTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.category = ServiceCategory.objects.create(name="Color", salon=self.salon)
        self.service = Service.objects.create(
            name="Single Process Color", category=self.category,
            service_minutes=45, external_id="svc-color",
        )
        self.level = StaffLevel.objects.create(name="Level 6", salon=self.salon)
        self.other_level = StaffLevel.objects.create(name="Level 8", salon=self.salon)

    # -- bulk_create -------------------------------------------------
    def test_bulk_create_duplicate_against_db_rejected(self):
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level, amount=Decimal("85.00"))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ServicePrice.objects.bulk_create([ServicePrice(
                    service=self.service, staff_level=self.level,
                    amount=Decimal("90.00"))])
        self.assertEqual(ServicePrice.objects.count(), 1)

    def test_bulk_create_intra_batch_duplicate_rejected_writes_nothing(self):
        batch = [
            ServicePrice(service=self.service, staff_level=self.level,
                         amount=Decimal("85.00")),
            ServicePrice(service=self.service, staff_level=self.level,
                         amount=Decimal("90.00")),
        ]
        with self.assertRaises(IntegrityError):
            ServicePrice.objects.bulk_create(batch)
        self.assertEqual(ServicePrice.objects.count(), 0)

    def test_bulk_create_service_external_id_intra_batch_duplicate(self):
        batch = [
            Service(name="A", category=self.category, service_minutes=30,
                    external_id="svc-dup"),
            Service(name="B", category=self.category, service_minutes=30,
                    external_id="svc-dup"),
        ]
        with self.assertRaises(IntegrityError):
            Service.objects.bulk_create(batch)
        self.assertEqual(Service.objects.count(), 1)  # only setUp's service

    def test_bulk_create_clean_batch_passes(self):
        ServicePrice.objects.bulk_create([
            ServicePrice(service=self.service, staff_level=self.level,
                         amount=Decimal("85.00")),
            ServicePrice(service=self.service, staff_level=self.other_level,
                         amount=Decimal("95.00")),
        ])
        self.assertEqual(ServicePrice.objects.count(), 2)
        # Blank external_id is outside the condition: duplicates allowed.
        Service.objects.bulk_create([
            Service(name="Haircut", category=self.category, service_minutes=30),
            Service(name="Blowout", category=self.category, service_minutes=30),
        ])
        self.assertEqual(Service.objects.filter(external_id="").count(), 2)

    # -- bulk_update -------------------------------------------------
    def test_bulk_update_into_duplicate_rejected(self):
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level, amount=Decimal("85.00"))
        price = ServicePrice.objects.create(
            service=self.service, staff_level=self.other_level,
            amount=Decimal("95.00"))
        price.staff_level = self.level
        with self.assertRaises(IntegrityError):
            ServicePrice.objects.bulk_update([price], fields=["staff_level"])
        price.refresh_from_db()
        self.assertEqual(price.staff_level, self.other_level)

    # -- queryset update() -------------------------------------------
    def test_update_into_duplicate_rejected(self):
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level, amount=Decimal("85.00"))
        price = ServicePrice.objects.create(
            service=self.service, staff_level=self.other_level,
            amount=Decimal("95.00"))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ServicePrice.objects.filter(pk=price.pk).update(
                    staff_level=self.level)
        price.refresh_from_db()
        self.assertEqual(price.staff_level, self.other_level)

    def test_update_service_external_id_into_duplicate_rejected(self):
        other = Service.objects.create(
            name="Balayage", category=self.category, service_minutes=90,
            external_id="svc-balayage")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Service.objects.filter(pk=other.pk).update(
                    external_id="svc-color")
        other.refresh_from_db()
        self.assertEqual(other.external_id, "svc-balayage")

    def test_update_multirow_to_same_unique_value_rejected(self):
        Service.objects.create(
            name="Balayage", category=self.category, service_minutes=90,
            external_id="svc-balayage")
        with self.assertRaises(IntegrityError):
            Service.objects.all().update(external_id="svc-same")
        self.assertEqual(
            Service.objects.filter(external_id="svc-same").count(), 0)

    def test_update_constrained_field_to_clean_value_passes(self):
        changed = Service.objects.filter(pk=self.service.pk).update(
            external_id="svc-colour")
        self.assertEqual(changed, 1)
        self.service.refresh_from_db()
        self.assertEqual(self.service.external_id, "svc-colour")

    def test_update_unconstrained_field_passes_through(self):
        price = ServicePrice.objects.create(
            service=self.service, staff_level=self.level, amount=Decimal("85.00"))
        changed = ServicePrice.objects.filter(pk=price.pk).update(active=False)
        self.assertEqual(changed, 1)
        price.refresh_from_db()
        self.assertFalse(price.active)

    def test_update_expression_on_constrained_field_refused(self):
        with self.assertRaises(IntegrityError):
            Service.objects.filter(pk=self.service.pk).update(
                external_id=F("name"))
