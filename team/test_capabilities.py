"""The capability rule: who performs what (team.capabilities).

Pins the three rules in order — explicit rows rule, the price
book derives, an unpriced service is open — and the seed command's
promise: materialise the derivation, never flip an edit.
"""

from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.capabilities import performer_ids, performs, seed_salon_capabilities
from team.models import StaffMember, StaffService


class CapabilityRuleTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Cap Salon", timezone="UTC")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color"
        )
        self.level_a = StaffLevel.objects.create(
            salon=self.salon, name="Level A"
        )
        self.level_b = StaffLevel.objects.create(
            salon=self.salon, name="Level B"
        )
        self.ana = StaffMember.objects.create(
            salon=self.salon, display_name="Ana", staff_level=self.level_a
        )
        self.bea = StaffMember.objects.create(
            salon=self.salon, display_name="Bea", staff_level=self.level_b
        )
        self.cut = Service.objects.create(
            category=self.category, name="Full Color", service_minutes=90
        )

    def _price(self, service, level):
        return ServicePrice.objects.create(
            service=service, staff_level=level, amount=Decimal("80.00")
        )

    def test_priced_level_performs_unpriced_does_not(self):
        self._price(self.cut, self.level_a)
        self.assertTrue(performs(self.ana, self.cut))
        self.assertFalse(performs(self.bea, self.cut))
        self.assertEqual(performer_ids(self.salon, self.cut), {self.ana.pk})

    def test_unpriced_service_is_open(self):
        self.assertIsNone(performer_ids(self.salon, self.cut))
        self.assertTrue(performs(self.ana, self.cut))
        self.assertTrue(performs(self.bea, self.cut))

    def test_member_without_level_does_not_derive(self):
        self._price(self.cut, self.level_a)
        no_level = StaffMember.objects.create(
            salon=self.salon, display_name="No Level"
        )
        self.assertFalse(performs(no_level, self.cut))

    def test_explicit_rows_rule_the_service(self):
        self._price(self.cut, self.level_a)
        StaffService.objects.create(
            staff_member=self.ana, service=self.cut, enabled=False
        )
        StaffService.objects.create(
            staff_member=self.bea, service=self.cut, enabled=True
        )
        self.assertFalse(performs(self.ana, self.cut))
        self.assertTrue(performs(self.bea, self.cut))
        self.assertEqual(performer_ids(self.salon, self.cut), {self.bea.pk})

    def test_rows_for_one_service_leave_others_derived(self):
        other = Service.objects.create(
            category=self.category, name="Gloss", service_minutes=30
        )
        self._price(other, self.level_b)
        StaffService.objects.create(
            staff_member=self.ana, service=self.cut, enabled=True
        )
        self.assertTrue(performs(self.bea, other))
        self.assertFalse(performs(self.ana, other))

    def test_new_member_has_no_row_on_a_configured_service(self):
        StaffService.objects.create(
            staff_member=self.ana, service=self.cut, enabled=True
        )
        new_hire = StaffMember.objects.create(
            salon=self.salon, display_name="New Hire",
            staff_level=self.level_a,
        )
        self.assertFalse(performs(new_hire, self.cut))

    def test_seed_materialises_the_derivation(self):
        self._price(self.cut, self.level_a)
        created, enabled = seed_salon_capabilities(self.salon)
        self.assertEqual(created, 2)
        self.assertEqual(enabled, 1)
        self.assertTrue(
            StaffService.objects.get(
                staff_member=self.ana, service=self.cut
            ).enabled
        )
        self.assertFalse(
            StaffService.objects.get(
                staff_member=self.bea, service=self.cut
            ).enabled
        )

    def test_seed_unpriced_service_enables_everyone(self):
        created, enabled = seed_salon_capabilities(self.salon)
        self.assertEqual((created, enabled), (2, 2))

    def test_seed_never_flips_an_edit_and_is_idempotent(self):
        row = StaffService.objects.create(
            staff_member=self.bea, service=self.cut, enabled=True
        )
        self._price(self.cut, self.level_a)
        created, _ = seed_salon_capabilities(self.salon)
        self.assertEqual(created, 1)  # only Ana's row was missing
        row.refresh_from_db()
        self.assertTrue(row.enabled)
        created_again, _ = seed_salon_capabilities(self.salon)
        self.assertEqual(created_again, 0)

    def test_seed_command_runs(self):
        self._price(self.cut, self.level_a)
        call_command("seed_staff_services")
        self.assertEqual(StaffService.objects.count(), 2)


class CapabilityEditingTests(TestCase):
    """The modal saves: materialise one service's list, one
    member's list, or copy a member's effective set — after
    which rows rule and the price book no longer speaks for
    what was saved."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Edit Salon", timezone="UTC")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color"
        )
        self.level_a = StaffLevel.objects.create(
            salon=self.salon, name="Level A"
        )
        self.level_b = StaffLevel.objects.create(
            salon=self.salon, name="Level B"
        )
        self.ana = StaffMember.objects.create(
            salon=self.salon, display_name="Ana", staff_level=self.level_a
        )
        self.bea = StaffMember.objects.create(
            salon=self.salon, display_name="Bea", staff_level=self.level_b
        )
        self.cut = Service.objects.create(
            category=self.category, name="Full Color", service_minutes=90
        )
        self.gloss = Service.objects.create(
            category=self.category, name="Gloss", service_minutes=30
        )
        ServicePrice.objects.create(
            service=self.cut, staff_level=self.level_a,
            amount=Decimal("80.00"),
        )

    def test_performer_map_reads_derivation_and_rows(self):
        from team.capabilities import performer_map

        result = performer_map(self.salon)
        self.assertEqual(result[self.cut.pk], {self.ana.pk})
        # The unpriced service is open: the whole active team.
        self.assertEqual(
            result[self.gloss.pk], {self.ana.pk, self.bea.pk}
        )

    def test_set_service_performers_materialises_the_list(self):
        from team.capabilities import performer_map, set_service_performers

        set_service_performers(self.cut, {self.bea.pk})
        self.assertEqual(StaffService.objects.filter(service=self.cut).count(), 2)
        self.assertEqual(performer_map(self.salon)[self.cut.pk], {self.bea.pk})
        # Rows rule now: pricing Ana's level no longer adds her.
        self.assertFalse(performs(self.ana, self.cut))

    def test_set_member_services_materialises_the_member(self):
        from team.capabilities import set_member_services

        set_member_services(self.bea, {self.gloss.pk})
        self.assertTrue(performs(self.bea, self.gloss))
        self.assertFalse(performs(self.bea, self.cut))
        # Ana is untouched in effect: ruling Bea's list
        # completed Full Color's grid with Ana's derived
        # truth written down, never dropped.
        self.assertTrue(performs(self.ana, self.cut))
        self.assertTrue(
            StaffService.objects.get(
                staff_member=self.ana, service=self.cut
            ).enabled
        )

    def test_copy_member_services_mirrors_the_effective_set(self):
        from team.capabilities import copy_member_services

        copy_member_services(self.ana, self.bea)
        self.assertTrue(performs(self.bea, self.cut))
        self.assertTrue(performs(self.bea, self.gloss))
        # Bea's own derivation is replaced by the mirror.
        self.assertEqual(
            StaffService.objects.filter(staff_member=self.bea).count(), 2
        )
