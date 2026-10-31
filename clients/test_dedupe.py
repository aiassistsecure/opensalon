from django.test import TestCase

from clients.dedupe import (
    find_duplicate_candidates,
    normalize_email,
    normalize_phone,
)
from clients.models import Client
from saloncore.models import Salon


def make(salon, first, last, **kw):
    return Client.objects.create(
        salon=salon, first_name=first, last_name=last, **kw
    )


class NormalizeTests(TestCase):
    def test_email_case_and_whitespace(self):
        self.assertEqual(normalize_email("  Amy@Example.COM "), "amy@example.com")
        self.assertEqual(normalize_email(""), "")
        self.assertEqual(normalize_email(None), "")

    def test_phone_punctuation_and_country_code(self):
        for raw in ("(555) 010-1234", "555.010.1234", "+1 555 010 1234",
                    "1-555-010-1234", "5550101234"):
            self.assertEqual(normalize_phone(raw), "5550101234", raw)
        self.assertEqual(normalize_phone(""), "")
        self.assertEqual(normalize_phone(None), "")
        self.assertEqual(normalize_phone("---"), "")


class FindDuplicateCandidatesTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        # Email duplicates: differ only by case/whitespace.
        self.amy = make(self.salon, "Amy", "Smith",
                        email="Amy@Example.com", phone="555-0101")
        self.amy2 = make(self.salon, "Amelia", "Smith",
                         email=" amy@example.com ", phone="555-9999")
        # Phone duplicates: differ only by punctuation/country code.
        self.bob = make(self.salon, "Bob", "Adams",
                        email="bob@example.com", phone="(555) 010-2222")
        self.bob2 = make(self.salon, "Robert", "Adams",
                         email="robert@example.com", phone="+1 555.010.2222")
        # Unique client: no group.
        self.zoe = make(self.salon, "Zoe", "Lee",
                        email="zoe@example.com", phone="555-3333")
        # Blank contact fields: must never group.
        self.blank1 = make(self.salon, "No", "Contact", email="", phone="")
        self.blank2 = make(self.salon, "None", "Contact", email="", phone="")
        # Inactive duplicate of amy's email: excluded.
        self.inactive = make(self.salon, "Amy", "Old",
                             email="amy@example.com", phone="555-0101",
                             active=False)
        # Same email in another salon: isolated when salon-scoped.
        self.other_amy = make(self.other, "Amy", "Smith",
                              email="amy@example.com", phone="555-7777")

    def groups(self, **kw):
        return find_duplicate_candidates(**kw)

    def by_key(self, groups):
        return {(g["key_type"], g["key"]): g["clients"] for g in groups}

    def test_groups_by_normalized_email(self):
        groups = self.by_key(self.groups(salon=self.salon))
        # Ordered by last name, first name: Amelia before Amy.
        self.assertEqual(groups[("email", "amy@example.com")],
                         [self.amy2, self.amy])

    def test_groups_by_normalized_phone(self):
        groups = self.by_key(self.groups(salon=self.salon))
        self.assertEqual(groups[("phone", "5550102222")],
                         [self.bob, self.bob2])

    def test_only_groups_of_two_or_more(self):
        groups = self.groups(salon=self.salon)
        self.assertEqual(len(groups), 2)
        flat = [c for g in groups for c in g["clients"]]
        self.assertNotIn(self.zoe, flat)

    def test_blank_email_and_phone_never_group(self):
        flat = [c for g in self.groups(salon=self.salon) for c in g["clients"]]
        self.assertNotIn(self.blank1, flat)
        self.assertNotIn(self.blank2, flat)

    def test_inactive_clients_excluded(self):
        flat = [c for g in self.groups() for c in g["clients"]]
        self.assertNotIn(self.inactive, flat)
        # amy's phone 555-0101 is shared only with the inactive record.
        self.assertNotIn(("phone", "5550101"), self.by_key(self.groups()))

    def test_salon_scoping_isolates_other_salon(self):
        groups = self.by_key(self.groups(salon=self.salon))
        self.assertNotIn(self.other_amy,
                         groups[("email", "amy@example.com")])
        other_groups = self.groups(salon=self.other)
        self.assertEqual(other_groups, [])

    def test_group_shape_and_deterministic_order(self):
        groups = self.groups(salon=self.salon)
        self.assertEqual([g["key_type"] for g in groups], ["email", "phone"])
        for g in groups:
            self.assertEqual(set(g), {"key_type", "key", "clients"})
            self.assertGreaterEqual(len(g["clients"]), 2)
        self.assertEqual(groups, self.groups(salon=self.salon))

    def test_pair_sharing_both_keys_appears_in_both_groups(self):
        make(self.salon, "Amy", "Clone", email="AMY@example.com",
             phone="555 0101")
        groups = self.by_key(self.groups(salon=self.salon))
        self.assertIn("5550101", [k for t, k in groups if t == "phone"])
        self.assertEqual(len(groups[("email", "amy@example.com")]), 3)

    def test_read_only_never_merges_or_deletes(self):
        before = Client.objects.count()
        self.groups()
        self.groups(salon=self.salon)
        self.assertEqual(Client.objects.count(), before)
        self.assertTrue(Client.objects.filter(pk=self.amy.pk).exists())
        self.assertTrue(Client.objects.filter(pk=self.amy2.pk).exists())
