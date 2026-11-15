"""Tests for --format text|json on set_service_performers.

Mirrors the sibling format tests (copy_member_services):
default text output is byte-identical, explicit text matches,
json prints exactly one object carrying the same facts, and
an invalid format raises CommandError. Fixtures are tiny
synthetic records.
"""
import io
import json
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel,
)
from team.capabilities import performs
from team.models import StaffMember, StaffService


def _run(name, **kwargs):
    out = io.StringIO()
    call_command(name, stdout=out, **kwargs)
    return out.getvalue()


class SetServicePerformersFormatTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Perf Salon", timezone="UTC")
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

    def _expected_text(self, dry_run=False):
        describe = (
            f"StaffService service={self.cut} "
            f"service_id={self.cut.pk} "
            f"staff_member_ids=[{self.bea.pk}] "
            f"enabled=1 of 2 members")
        if dry_run:
            return f"Dry run: would set {describe} -- no rows written.\n"
        return f"Set {describe}.\n"

    def test_default_text_output_unchanged(self):
        out = _run("set_service_performers", service_id=self.cut.pk,
                   staff_member_id=[self.bea.pk])
        self.assertEqual(out, self._expected_text())
        self.assertTrue(performs(self.bea, self.cut))

    def test_explicit_text_matches_default(self):
        out = _run("set_service_performers", service_id=self.cut.pk,
                   staff_member_id=[self.bea.pk], format="text")
        self.assertEqual(out, self._expected_text())

    def test_explicit_text_dry_run_matches_default(self):
        out = _run("set_service_performers", service_id=self.cut.pk,
                   staff_member_id=[self.bea.pk], dry_run=True,
                   format="text")
        self.assertEqual(out, self._expected_text(dry_run=True))

    def test_json_parses_as_one_object_with_correct_values(self):
        out = _run("set_service_performers", service_id=self.cut.pk,
                   staff_member_id=[self.bea.pk], format="json")
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertNotIn("Set", out)
        self.assertEqual(json.loads(out), {
            "service_id": self.cut.pk,
            "staff_member_ids": [self.bea.pk],
            "enabled": 1,
            "total_members": 2,
            "dry_run": False,
        })
        self.assertTrue(performs(self.bea, self.cut))
        self.assertFalse(performs(self.ana, self.cut))

    def test_json_dry_run_never_calls_writer(self):
        with mock.patch(
                "team.management.commands.set_service_performers"
                ".set_service_performers") as writer:
            out = _run("set_service_performers", service_id=self.cut.pk,
                       staff_member_id=[self.bea.pk], dry_run=True,
                       format="json")
        writer.assert_not_called()
        self.assertEqual(len(out.strip().splitlines()), 1)
        self.assertEqual(json.loads(out), {
            "service_id": self.cut.pk,
            "staff_member_ids": [self.bea.pk],
            "enabled": 1,
            "total_members": 2,
            "dry_run": True,
        })
        self.assertEqual(StaffService.objects.count(), 0)

    def test_json_via_cli(self):
        out = io.StringIO()
        call_command(
            "set_service_performers", "--service-id", str(self.cut.pk),
            "--staff-member-id", str(self.bea.pk),
            "--format", "json", stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data["service_id"], self.cut.pk)
        self.assertEqual(data["staff_member_ids"], [self.bea.pk])
        self.assertFalse(data["dry_run"])

    def test_invalid_format_rejected(self):
        rows_before = StaffService.objects.count()
        with self.assertRaises(CommandError):
            _run("set_service_performers", service_id=self.cut.pk,
                 staff_member_id=[self.bea.pk], format="bogus")
        self.assertEqual(StaffService.objects.count(), rows_before)
        with self.assertRaises(CommandError):
            _run("set_service_performers", service_id=999999,
                 staff_member_id=[], format="json")
