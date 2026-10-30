from django.test import TestCase

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember


class StaffMemberModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.level = StaffLevel.objects.create(name="Level 6", salon=self.salon)

    def test_creation_and_salon_fk(self):
        member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon
        )
        self.assertEqual(member.salon, self.salon)
        self.assertIn(member, list(self.salon.staff_members.all()))
        self.assertTrue(member.active)

    def test_str_returns_display_name(self):
        member = StaffMember(display_name="Sonia Taylor", salon=self.salon)
        self.assertEqual(str(member), "Sonia Taylor")

    def test_level_link(self):
        member = StaffMember.objects.create(
            display_name="Eva Bonilla", salon=self.salon, staff_level=self.level
        )
        self.assertEqual(member.staff_level, self.level)
        self.assertIn(member, list(self.level.members.all()))

    def test_level_is_optional(self):
        member = StaffMember.objects.create(
            display_name="No Level", salon=self.salon
        )
        self.assertIsNone(member.staff_level)

    def test_level_delete_sets_null(self):
        member = StaffMember.objects.create(
            display_name="Dawn Davalos", salon=self.salon, staff_level=self.level
        )
        self.level.delete()
        member.refresh_from_db()
        self.assertIsNone(member.staff_level)

    def test_online_bookable_defaults_true(self):
        member = StaffMember.objects.create(
            display_name="Default Bookable", salon=self.salon
        )
        member.refresh_from_db()
        self.assertTrue(member.online_bookable)

    def test_online_bookable_false_case(self):
        member = StaffMember.objects.create(
            display_name="Not Bookable", salon=self.salon, online_bookable=False
        )
        member.refresh_from_db()
        self.assertFalse(member.online_bookable)

    def test_ordering_by_display_name(self):
        StaffMember.objects.create(display_name="Zoe", salon=self.salon)
        StaffMember.objects.create(display_name="Amy", salon=self.salon)
        names = list(StaffMember.objects.values_list("display_name", flat=True))
        self.assertEqual(names, ["Amy", "Zoe"])
