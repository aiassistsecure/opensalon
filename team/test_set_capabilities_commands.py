"""Tests for set_service_performers / set_member_services commands.

Thin wrappers over the existing team.capabilities setters.
--dry-run is NEDB-safe: it validates via the read-only
validate_* helpers and never calls the writer (mocked writers
assert this, so the tests fail on a write-then-rollback
mechanism even on SQLite), and invalid-input dry-runs still
raise CommandError. Fixtures are tiny synthetic records.
"""
import io
from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel,
)
from team.capabilities import (
    performs, validate_set_member_services,
    validate_set_service_performers,
)
from team.models import StaffMember, StaffService


def _run(name, **kwargs):
    out = io.StringIO()
    call_command(name, stdout=out, **kwargs)
    return out.getvalue()


class Fixture(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Cap Salon", timezone="UTC")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Color")
        level = StaffLevel.objects.create(salon=self.salon, name="Level A")
        self.ana = StaffMember.objects.create(
            salon=self.salon, display_name="Ana", staff_level=level,
            external_id="staff-ana")
        self.bea = StaffMember.objects.create(
            salon=self.salon, display_name="Bea", staff_level=level,
            external_id="staff-bea")
        self.cut = Service.objects.create(
            category=cat, name="Full Color", service_minutes=90,
            external_id="svc-cut")
        self.gloss = Service.objects.create(
            category=cat, name="Gloss", service_minutes=30,
            external_id="svc-gloss")
        ServicePrice.objects.create(
            service=self.cut, staff_level=level, amount=Decimal("80.00"))


class SetServicePerformersCommandTests(Fixture):
    def test_real_run_materialises_the_list(self):
        out = _run("set_service_performers", service_id=self.cut.pk,
                   staff_member_id=[self.bea.pk])
        self.assertIn(f"service_id={self.cut.pk}", out)
        self.assertEqual(
            StaffService.objects.filter(service=self.cut).count(), 2)
        self.assertTrue(performs(self.bea, self.cut))
        self.assertFalse(performs(self.ana, self.cut))

    def test_resolves_service_and_members_by_external_id(self):
        _run("set_service_performers", service_external_id="svc-cut",
             staff_member_external_id=["staff-ana"])
        self.assertTrue(performs(self.ana, self.cut))
        self.assertFalse(performs(self.bea, self.cut))

    def test_dry_run_never_calls_writer_and_writes_nothing(self):
        with mock.patch(
                "team.management.commands.set_service_performers"
                ".set_service_performers") as writer:
            out = _run("set_service_performers", service_id=self.cut.pk,
                       staff_member_id=[self.bea.pk], dry_run=True)
        writer.assert_not_called()
        self.assertIn("Dry run: would set", out)
        self.assertIn(f"staff_member_ids=[{self.bea.pk}]", out)
        self.assertEqual(StaffService.objects.count(), 0)

    def test_dry_run_invalid_member_still_raises_and_writes_nothing(self):
        with mock.patch(
                "team.management.commands.set_service_performers"
                ".set_service_performers") as writer:
            with self.assertRaises(CommandError):
                _run("set_service_performers", service_id=self.cut.pk,
                     staff_member_id=[999999], dry_run=True)
        writer.assert_not_called()
        self.assertEqual(StaffService.objects.count(), 0)

    def test_unknown_service_raises_in_dry_run_and_real_run(self):
        for dry in (True, False):
            with self.assertRaises(CommandError):
                _run("set_service_performers", service_id=999999,
                     staff_member_id=[], dry_run=dry)
        self.assertEqual(StaffService.objects.count(), 0)


class SetMemberServicesCommandTests(Fixture):
    def test_real_run_materialises_the_member(self):
        out = _run("set_member_services", staff_member_id=self.bea.pk,
                   service_id=[self.gloss.pk])
        self.assertIn(f"staff_member_id={self.bea.pk}", out)
        self.assertTrue(performs(self.bea, self.gloss))
        self.assertFalse(performs(self.bea, self.cut))
        # Completing the grid never drops a colleague.
        self.assertTrue(performs(self.ana, self.cut))

    def test_resolves_member_and_services_by_external_id(self):
        _run("set_member_services", staff_member_external_id="staff-bea",
             service_external_id=["svc-gloss"])
        self.assertTrue(performs(self.bea, self.gloss))
        self.assertFalse(performs(self.bea, self.cut))

    def test_dry_run_never_calls_writer_and_writes_nothing(self):
        with mock.patch(
                "team.management.commands.set_member_services"
                ".set_member_services") as writer:
            out = _run("set_member_services",
                       staff_member_id=self.bea.pk,
                       service_id=[self.gloss.pk], dry_run=True)
        writer.assert_not_called()
        self.assertIn("Dry run: would set", out)
        self.assertIn(f"service_ids=[{self.gloss.pk}]", out)
        self.assertEqual(StaffService.objects.count(), 0)

    def test_dry_run_invalid_service_still_raises_and_writes_nothing(self):
        with mock.patch(
                "team.management.commands.set_member_services"
                ".set_member_services") as writer:
            with self.assertRaises(CommandError):
                _run("set_member_services",
                     staff_member_id=self.bea.pk,
                     service_id=[999999], dry_run=True)
        writer.assert_not_called()
        self.assertEqual(StaffService.objects.count(), 0)

    def test_unknown_member_raises_in_dry_run_and_real_run(self):
        for dry in (True, False):
            with self.assertRaises(CommandError):
                _run("set_member_services", staff_member_id=999999,
                     service_id=[], dry_run=dry)
        self.assertEqual(StaffService.objects.count(), 0)


class ValidateHelpersTests(Fixture):
    def test_validate_helpers_write_nothing(self):
        self.assertEqual(
            validate_set_service_performers(self.cut, [self.ana.pk]),
            {self.ana.pk})
        self.assertEqual(
            validate_set_member_services(self.bea, [self.gloss.pk]),
            {self.gloss.pk})
        self.assertEqual(StaffService.objects.count(), 0)

    def test_validate_helpers_reject_unknown_ids(self):
        with self.assertRaises(ValidationError):
            validate_set_service_performers(self.cut, [999999])
        with self.assertRaises(ValidationError):
            validate_set_member_services(self.bea, [999999])
        self.assertEqual(StaffService.objects.count(), 0)
