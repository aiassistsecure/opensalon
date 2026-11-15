"""Tests for the repair_staff_levels --salon-id bridge.

--salon-id selects an existing salon by pk and takes precedence
over --salon; a nonexistent id raises CommandError and writes
nothing; without --salon-id the name path is unchanged.
Unit logic only, no real salon data.
"""
import io
import json
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import (
    Salon, Service, ServiceCategory, ServicePrice, StaffLevel,
)
from team.models import StaffMember

CAT_ID = "RqYB0nJ02216iNO36VAwzA"  # Artist Level 6's category id
UNKNOWN_ID = "H4zBPQ63XrW87rOtEvXClA"


class RepairStaffLevelsSalonIdTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Mint", timezone="America/New_York")
        self.other = Salon.objects.create(
            name="Other", timezone="America/New_York")
        for salon in (self.salon, self.other):
            named = StaffLevel.objects.create(
                salon=salon, name="Artist Level 6")
            guid = StaffLevel.objects.create(salon=salon, name=CAT_ID)
            unknown = StaffLevel.objects.create(
                salon=salon, name=UNKNOWN_ID)
            category = ServiceCategory.objects.create(
                salon=salon, name="Hair")
            service = Service.objects.create(
                category=category, name="Women's Haircut",
                service_minutes=60)
            ServicePrice.objects.create(
                service=service, staff_level=guid,
                amount=Decimal("65.00"))
            ServicePrice.objects.create(
                service=service, staff_level=unknown,
                amount=Decimal("70.00"))
            StaffMember.objects.create(
                salon=salon, display_name="Dawn Davalos",
                staff_level=guid)
            if salon is self.salon:
                self.named, self.guid, self.unknown = named, guid, unknown
            else:
                self.other_guid, self.other_unknown = guid, unknown
        staff_file = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False)
        json.dump([{
            "staffCategoryId": CAT_ID,
            "staffCategoryName": "Artist Level 6",
        }], staff_file)
        staff_file.close()
        self.staff_path = staff_file.name

    def _run(self, **kwargs):
        out = io.StringIO()
        call_command("repair_staff_levels", staff=self.staff_path,
                     stdout=out, **kwargs)
        return out.getvalue()

    def test_salon_id_selects_existing_salon(self):
        out = self._run(salon_id=self.salon.pk)
        self.assertIn("salon=Mint", out)
        self.assertIn("merged=1", out)
        self.assertFalse(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())
        # The other salon is untouched.
        self.assertTrue(
            StaffLevel.objects.filter(pk=self.other_guid.pk).exists())

    def test_salon_id_cli_flag_selects_existing_salon(self):
        out = io.StringIO()
        call_command("repair_staff_levels",
                     "--salon-id", str(self.salon.pk),
                     staff=self.staff_path, stdout=out)
        self.assertIn("salon=Mint", out.getvalue())
        self.assertFalse(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())

    def test_salon_id_nonexistent_raises_and_writes_nothing(self):
        with self.assertRaises(CommandError):
            self._run(salon_id=self.salon.pk + 1000)
        # No writes: id levels still present under their id names,
        # unknown levels not renamed, in both salons.
        self.assertTrue(
            StaffLevel.objects.filter(pk=self.guid.pk, name=CAT_ID).exists())
        self.assertTrue(StaffLevel.objects.filter(
            pk=self.unknown.pk, name=UNKNOWN_ID).exists())
        self.assertTrue(StaffLevel.objects.filter(
            pk=self.other_guid.pk, name=CAT_ID).exists())
        self.assertEqual(Salon.objects.count(), 2)

    def test_salon_id_takes_precedence_over_salon_name(self):
        out = self._run(salon_id=self.salon.pk, salon="Other")
        self.assertIn("salon=Mint", out)
        self.assertFalse(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())
        self.assertTrue(
            StaffLevel.objects.filter(pk=self.other_guid.pk).exists())

    def test_name_path_unchanged_without_salon_id(self):
        out = self._run(salon="Mint")
        self.assertIn("salon=Mint", out)
        self.assertFalse(
            StaffLevel.objects.filter(pk=self.guid.pk).exists())
        self.assertTrue(
            StaffLevel.objects.filter(pk=self.other_guid.pk).exists())
