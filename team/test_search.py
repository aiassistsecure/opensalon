from django.test import TestCase

from saloncore.models import Salon, StaffLevel
from team.models import StaffMember
from team.search import search_staff


class SearchStaffTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.l6 = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.l1 = StaffLevel.objects.create(salon=self.salon, name="Level 1")

    def make(self, name, level=None, salon=None, **kw):
        return StaffMember.objects.create(
            salon=salon or self.salon, display_name=name,
            staff_level=level, **kw)

    def results(self, query=None, salon=None, **kw):
        return list(search_staff(salon or self.salon, query, **kw))

    def test_name_case_insensitive_substring(self):
        amy = self.make("Amy Smith", self.l6)
        self.make("Bob Adams", self.l1)
        self.assertEqual(self.results("amy"), [amy])
        self.assertEqual(self.results("SMITH"), [amy])
        self.assertEqual(self.results("mit"), [amy])
        self.assertEqual(self.results("zzz"), [])

    def test_level_name_match(self):
        amy = self.make("Amy Smith", self.l6)
        bob = self.make("Bob Adams", self.l1)
        self.assertEqual(self.results("level 6"), [amy])
        self.assertEqual(self.results("LEVEL 1"), [bob])
        self.assertEqual(self.results("level"), [amy, bob])

    def test_member_without_level_matches_by_name_only(self):
        solo = self.make("Solo Person")
        self.assertEqual(self.results("solo"), [solo])
        self.assertEqual(self.results("level"), [])

    def test_empty_query_returns_all_ordered_by_name_then_id(self):
        bob = self.make("Bob Adams", self.l1)
        amy = self.make("Amy Smith", self.l6)
        for blank in ("", "   ", None):
            self.assertEqual(self.results(blank), [amy, bob])

    def test_query_is_stripped(self):
        amy = self.make("Amy Smith", self.l6)
        self.assertEqual(self.results("  amy  "), [amy])

    def test_salon_isolation(self):
        mine = self.make("Amy Smith", self.l6)
        other_level = StaffLevel.objects.create(
            salon=self.other, name="Level 6")
        foreign = self.make(
            "Amy Smith", other_level, salon=self.other)
        self.assertEqual(self.results("amy"), [mine])
        self.assertEqual(self.results("level 6"), [mine])
        self.assertEqual(self.results("amy", salon=self.other), [foreign])

    def test_active_filter_tri_state(self):
        active = self.make("Amy Active")
        inactive = self.make("Ian Inactive", active=False)
        self.assertEqual(self.results(), [active, inactive])
        self.assertEqual(self.results(active=True), [active])
        self.assertEqual(self.results(active=False), [inactive])

    def test_online_bookable_filter_tri_state(self):
        bookable = self.make("Amy Bookable")
        hidden = self.make("Hank Hidden", online_bookable=False)
        self.assertEqual(self.results(), [bookable, hidden])
        self.assertEqual(self.results(online_bookable=True), [bookable])
        self.assertEqual(self.results(online_bookable=False), [hidden])

    def test_flags_combine_with_query(self):
        amy = self.make("Amy Smith", self.l6, online_bookable=False)
        self.make("Amy Jones", self.l6)
        self.assertEqual(
            self.results("amy", online_bookable=False), [amy])
        self.assertEqual(
            self.results("level 6", active=True), self.results("level 6"))

    def test_returns_member_with_level(self):
        amy = self.make("Amy Smith", self.l6)
        found = self.results("amy")
        self.assertEqual(found[0].staff_level, self.l6)
        self.assertEqual(search_staff(self.salon, "amy").model, StaffMember)

    def test_read_only(self):
        self.make("Amy Smith", self.l6)
        self.results("amy")
        self.assertEqual(StaffMember.objects.count(), 1)
