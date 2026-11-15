"""Tests for --salon-id on seed_staff_services.

Mirrors the --salon-id bridge in import_staff (batch 1):
id selects the salon, beats --salon, and a nonexistent id
raises CommandError with no writes. Name path unchanged, and
--format (cycle 628) is preserved. Fixtures are tiny synthetic
records.
"""
import io
import json
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel,
)
from team.models import StaffMember, StaffService


def _run(name, **kwargs):
    out = io.StringIO()
    call_command(name, stdout=out, **kwargs)
    return out.getvalue()


def _make_salon(name):
    salon = Salon.objects.create(name=name, timezone="UTC")
    cat = ServiceCategory.objects.create(salon=salon, name="Color")
    level = StaffLevel.objects.create(salon=salon, name="Level A")
    member = StaffMember.objects.create(
        salon=salon, display_name="Ana", staff_level=level)
    cut = Service.objects.create(
        category=cat, name="Full Color", service_minutes=90)
    Service.objects.create(
        category=cat, name="Gloss", service_minutes=30)
    ServicePrice.objects.create(
        service=cut, staff_level=level, amount=Decimal("80.00"))
    return salon, member


class SeedStaffServicesSalonIdTests(TestCase):
    def test_salon_id_selects_existing_salon(self):
        salon, member = _make_salon("Id Salon")
        _make_salon("Other Salon")
        out = io.StringIO()
        # CLI form proves the --salon-id argument is wired.
        call_command("seed_staff_services", "--salon-id",
                     str(salon.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            f"seed_staff_services: salon=Id Salon created=2 enabled=2\n")
        self.assertEqual(StaffService.objects.count(), 2)
        self.assertEqual(
            StaffService.objects.filter(
                staff_member=member).count(), 2)

    def test_salon_id_nonexistent_raises_and_writes_nothing(self):
        _make_salon("Id Salon")
        with self.assertRaises(CommandError):
            _run("seed_staff_services", salon_id=999999)
        self.assertEqual(StaffService.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 1)

    def test_salon_id_unknown_with_dry_run_and_json_writes_nothing(self):
        _make_salon("Id Salon")
        with self.assertRaises(CommandError):
            _run("seed_staff_services", salon_id=999999, dry_run=True)
        with self.assertRaises(CommandError):
            _run("seed_staff_services", salon_id=999999, format="json")
        self.assertEqual(StaffService.objects.count(), 0)

    def test_salon_id_takes_precedence_over_salon_name(self):
        salon, member = _make_salon("Real Salon")
        _make_salon("Other Name")
        out = _run("seed_staff_services", salon_id=salon.pk,
                   salon="Other Name")
        self.assertIn("salon=Real Salon", out)
        self.assertNotIn("Other Name", out)
        self.assertEqual(StaffService.objects.count(), 2)
        self.assertEqual(
            StaffService.objects.filter(
                staff_member=member).count(), 2)

    def test_salon_name_path_unchanged(self):
        _make_salon("Named Salon")
        _make_salon("Other Salon")
        out = _run("seed_staff_services", salon="Named Salon")
        self.assertIn("salon=Named Salon", out)
        self.assertEqual(StaffService.objects.count(), 2)

    def test_salon_id_with_json_format(self):
        salon, _member = _make_salon("Id Salon")
        out = _run("seed_staff_services", salon_id=salon.pk,
                   format="json")
        self.assertEqual(json.loads(out), {
            "salons": [{"salon": "Id Salon", "created": 2,
                        "enabled": 2}],
            "dry_run": False,
        })
        self.assertEqual(StaffService.objects.count(), 2)

    def test_salon_id_with_dry_run_writes_nothing(self):
        salon, _member = _make_salon("Id Salon")
        out = _run("seed_staff_services", salon_id=salon.pk,
                   dry_run=True)
        self.assertIn("salon=Id Salon", out)
        self.assertIn("would_create=2", out)
        self.assertEqual(StaffService.objects.count(), 0)
