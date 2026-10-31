"""repair_staff_levels: rejoin the two halves of the price ladder."""
import json
import tempfile
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase

from saloncore.models import Salon, Service, ServiceCategory, ServicePrice, StaffLevel
from team.models import StaffMember

CAT_ID = "RqYB0nJ02216iNO36VAwzA"  # Artist Level 6's category id
UNKNOWN_ID = "H4zBPQ63XrW87rOtEvXClA"


class RepairStaffLevelsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint", timezone="America/New_York")
        self.named = StaffLevel.objects.create(salon=self.salon, name="Artist Level 6")
        self.guid = StaffLevel.objects.create(salon=self.salon, name=CAT_ID)
        self.unknown = StaffLevel.objects.create(salon=self.salon, name=UNKNOWN_ID)
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Women's Haircut", service_minutes=60
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.guid, amount=Decimal("65.00")
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.unknown, amount=Decimal("70.00")
        )
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dawn Davalos", staff_level=self.guid
        )
        staff_file = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        )
        json.dump([{
            "staffCategoryId": CAT_ID,
            "staffCategoryName": "Artist Level 6",
        }], staff_file)
        staff_file.close()
        self.staff_path = staff_file.name

    def run_repair(self):
        call_command(
            "repair_staff_levels", staff=self.staff_path, salon="Mint"
        )

    def test_merge_moves_prices_and_members_and_deletes_the_id_level(self):
        self.run_repair()
        self.assertFalse(StaffLevel.objects.filter(pk=self.guid.pk).exists())
        price = ServicePrice.objects.get(service=self.service, staff_level=self.named)
        self.assertEqual(price.amount, Decimal("65.00"))
        self.member.refresh_from_db()
        self.assertEqual(self.member.staff_level, self.named)

    def test_unknown_id_becomes_unassigned_but_keeps_its_prices(self):
        self.run_repair()
        self.unknown.refresh_from_db()
        self.assertEqual(self.unknown.name, "Unassigned ····XClA")
        self.assertEqual(
            ServicePrice.objects.filter(staff_level=self.unknown).count(), 1
        )

    def test_idempotent_second_run(self):
        self.run_repair()
        levels = sorted(StaffLevel.objects.values_list("name", flat=True))
        self.run_repair()
        self.assertEqual(
            levels, sorted(StaffLevel.objects.values_list("name", flat=True))
        )
