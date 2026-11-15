"""Tests for --format text|json on seed_staff_services.

Mirrors the sibling format tests (copy_member_services):
default text output is byte-identical, explicit text matches,
json prints exactly one object carrying the same facts, and
an invalid format raises CommandError. Fixtures are tiny
synthetic records.
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


class SeedStaffServicesFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Cap Salon", timezone="UTC")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Color")
        level_a = StaffLevel.objects.create(salon=self.salon, name="Level A")
        level_b = StaffLevel.objects.create(salon=self.salon, name="Level B")
        self.ana = StaffMember.objects.create(
            salon=self.salon, display_name="Ana", staff_level=level_a)
        self.bea = StaffMember.objects.create(
            salon=self.salon, display_name="Bea", staff_level=level_b)
        self.cut = Service.objects.create(
            category=cat, name="Full Color", service_minutes=90)
        Service.objects.create(
            category=cat, name="Gloss", service_minutes=30)
        ServicePrice.objects.create(
            service=self.cut, staff_level=level_a, amount=Decimal("80.00"))

    def _expected_text(self):
        return (f"seed_staff_services: salon={self.salon.name} "
                f"created=4 enabled=3\n")

    def _expected_dry_run_text(self):
        return (
            f"seed_staff_services dry-run: salon={self.salon.name} "
            f"staff_member_id={self.ana.pk} "
            f"would_create=2 would_enable=2\n"
            f"seed_staff_services dry-run: salon={self.salon.name} "
            f"staff_member_id={self.bea.pk} "
            f"would_create=2 would_enable=1\n"
            f"seed_staff_services dry-run: salon={self.salon.name} "
            f"would_create=4 would_enable=3 -- no rows created\n")

    def test_default_text_output_unchanged(self):
        out = _run("seed_staff_services")
        self.assertEqual(out, self._expected_text())
        self.assertEqual(StaffService.objects.count(), 4)

    def test_explicit_text_matches_default(self):
        out = _run("seed_staff_services", format="text")
        self.assertEqual(out, self._expected_text())

    def test_explicit_text_dry_run_matches_default(self):
        out = _run("seed_staff_services", dry_run=True, format="text")
        self.assertEqual(out, self._expected_dry_run_text())
        self.assertEqual(StaffService.objects.count(), 0)

    def test_json_parses_as_one_object_with_correct_values(self):
        out = _run("seed_staff_services", format="json")
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertNotIn("seed_staff_services:", out)
        self.assertEqual(json.loads(out), {
            "salons": [{
                "salon": self.salon.name,
                "created": 4,
                "enabled": 3,
            }],
            "dry_run": False,
        })
        self.assertEqual(StaffService.objects.count(), 4)

    def test_json_dry_run_carries_per_member_facts_and_writes_nothing(self):
        out = _run("seed_staff_services", dry_run=True, format="json")
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertNotIn("dry-run:", out)
        self.assertEqual(json.loads(out), {
            "salons": [{
                "salon": self.salon.name,
                "would_create": 4,
                "would_enable": 3,
                "per_member": [
                    {"staff_member_id": self.ana.pk,
                     "would_create": 2, "would_enable": 2},
                    {"staff_member_id": self.bea.pk,
                     "would_create": 2, "would_enable": 1},
                ],
            }],
            "dry_run": True,
        })
        self.assertEqual(StaffService.objects.count(), 0)

    def test_json_via_cli(self):
        out = io.StringIO()
        call_command("seed_staff_services", "--format", "json", stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["salons"][0]["salon"], self.salon.name)
        self.assertEqual(data["salons"][0]["created"], 4)
        self.assertFalse(data["dry_run"])

    def test_invalid_format_rejected(self):
        with self.assertRaises(CommandError):
            _run("seed_staff_services", format="bogus")
        self.assertEqual(StaffService.objects.count(), 0)
