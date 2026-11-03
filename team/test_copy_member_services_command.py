"""Tests for the copy_member_services management command.

Thin wrapper over team.capabilities.copy_member_services.
--dry-run is NEDB-safe: it previews the would-land effective
set via performer_map (reads only) and never calls the writer
(mocked writer asserts this, so the tests fail on a
write-then-rollback mechanism even on SQLite). Fixtures are
tiny synthetic records.
"""
import io
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel,
)
from team.capabilities import performs, set_member_services
from team.models import StaffMember, StaffService


def _run(name, **kwargs):
    out = io.StringIO()
    call_command(name, stdout=out, **kwargs)
    return out.getvalue()


class CopyMemberServicesCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Copy Salon", timezone="UTC")
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
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.outsider = StaffMember.objects.create(
            salon=other, display_name="Ola", external_id="staff-ola")

    def test_real_run_mirrors_the_source_effective_set(self):
        set_member_services(self.ana, [self.cut.pk])
        out = _run("copy_member_services", source_member_id=self.ana.pk,
                   target_member_id=self.bea.pk)
        self.assertIn(f"source_member_id={self.ana.pk}", out)
        self.assertIn(f"target_member_id={self.bea.pk}", out)
        self.assertIn(f"service_ids=[{self.cut.pk}]", out)
        self.assertTrue(performs(self.bea, self.cut))
        self.assertFalse(performs(self.bea, self.gloss))
        # The source is untouched.
        self.assertTrue(performs(self.ana, self.cut))
        self.assertFalse(performs(self.ana, self.gloss))

    def test_real_run_from_price_book_derived_set(self):
        _run("copy_member_services", source_member_id=self.ana.pk,
             target_member_id=self.bea.pk)
        self.assertTrue(performs(self.bea, self.cut))
        self.assertTrue(performs(self.bea, self.gloss))

    def test_resolves_members_by_external_id(self):
        set_member_services(self.ana, [self.gloss.pk])
        _run("copy_member_services",
             source_member_external_id="staff-ana",
             target_member_external_id="staff-bea")
        self.assertTrue(performs(self.bea, self.gloss))
        self.assertFalse(performs(self.bea, self.cut))

    def test_dry_run_previews_effective_set_and_never_calls_writer(self):
        with mock.patch(
                "team.management.commands.copy_member_services"
                ".copy_member_services") as writer:
            out = _run("copy_member_services",
                       source_member_id=self.ana.pk,
                       target_member_id=self.bea.pk, dry_run=True)
        writer.assert_not_called()
        self.assertIn("Dry run: would copy", out)
        # Price book: cut is priced for the shared level, gloss
        # is open -- both are in the source's effective set.
        self.assertIn(
            f"service_ids={sorted([self.cut.pk, self.gloss.pk])}", out)
        self.assertEqual(StaffService.objects.count(), 0)

    def test_dry_run_preview_matches_real_run(self):
        set_member_services(self.ana, [self.cut.pk])
        rows_before = sorted(StaffService.objects.values_list(
            "staff_member_id", "service_id", "enabled"))
        out = _run("copy_member_services", source_member_id=self.ana.pk,
                   target_member_id=self.bea.pk, dry_run=True)
        self.assertIn(f"service_ids=[{self.cut.pk}]", out)
        self.assertEqual(
            sorted(StaffService.objects.values_list(
                "staff_member_id", "service_id", "enabled")),
            rows_before)

    def test_out_of_salon_target_raises_and_writes_nothing(self):
        for dry in (True, False):
            with self.assertRaises(CommandError):
                _run("copy_member_services",
                     source_member_id=self.ana.pk,
                     target_member_id=self.outsider.pk, dry_run=dry)
            with self.assertRaises(CommandError):
                _run("copy_member_services",
                     source_member_id=self.ana.pk,
                     target_member_external_id="staff-ola", dry_run=dry)
        self.assertEqual(StaffService.objects.count(), 0)

    def test_unknown_member_raises_in_dry_run_and_real_run(self):
        for dry in (True, False):
            with self.assertRaises(CommandError):
                _run("copy_member_services", source_member_id=999999,
                     target_member_id=self.bea.pk, dry_run=dry)
            with self.assertRaises(CommandError):
                _run("copy_member_services",
                     source_member_id=self.ana.pk,
                     target_member_id=999999, dry_run=dry)
        self.assertEqual(StaffService.objects.count(), 0)

    def test_both_id_forms_for_one_member_raises(self):
        with self.assertRaises(CommandError):
            _run("copy_member_services", source_member_id=self.ana.pk,
                 source_member_external_id="staff-ana",
                 target_member_id=self.bea.pk)
        self.assertEqual(StaffService.objects.count(), 0)
