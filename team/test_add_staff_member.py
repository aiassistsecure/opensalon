from django.test import TestCase

from saloncore.models import Salon, StaffLevel
from team.add_staff_member import (
    add_staff_member, validate_add_staff_member)
from team.models import StaffMember


class AddStaffMemberTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6")
        self.other_level = StaffLevel.objects.create(
            salon=self.other, name="Level 6")

    def test_creates_member_with_all_fields(self):
        m = add_staff_member(
            self.salon, "  Dana Davalos  ", staff_level=self.level,
            online_bookable=False, email="dana@example.com",
            pin="1234")
        self.assertEqual(StaffMember.objects.count(), 1)
        self.assertEqual(
            (m.salon, m.display_name, m.staff_level,
             m.online_bookable, m.email, m.pin, m.active,
             m.external_id),
            (self.salon, "Dana Davalos", self.level, False,
             "dana@example.com", "1234", True, ""))

    def test_defaults_no_level_bookable_blank_email_pin(self):
        m = add_staff_member(self.salon, "Dana")
        self.assertEqual(
            (m.staff_level, m.online_bookable, m.email, m.pin),
            (None, True, "", ""))

    def test_blank_or_overlong_name_refused(self):
        for bad in ("", "   ", None, 123, "x" * 121):
            with self.assertRaises(ValueError):
                add_staff_member(self.salon, bad)
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_unsaved_salon_and_level_refused(self):
        with self.assertRaises(ValueError):
            add_staff_member(Salon(name="Unsaved"), "Dana")
        with self.assertRaises(ValueError):
            add_staff_member(
                self.salon, "Dana",
                staff_level=StaffLevel(salon=self.salon, name="L"))
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_cross_salon_level_refused(self):
        with self.assertRaises(ValueError):
            add_staff_member(
                self.salon, "Dana", staff_level=self.other_level)
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_non_bool_online_bookable_refused(self):
        with self.assertRaises(ValueError):
            add_staff_member(self.salon, "Dana", online_bookable="yes")
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_bad_email_refused(self):
        for bad in ("not-an-email", "dana@", "@example.com", 123,
                    "a" * 250 + "@x.co"):
            with self.assertRaises(ValueError):
                add_staff_member(self.salon, "Dana", email=bad)
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_duplicate_email_active_member_refused_case_insensitive(self):
        add_staff_member(self.salon, "Dana", email="dana@example.com")
        with self.assertRaises(ValueError):
            add_staff_member(
                self.other, "Other Dana", email="DANA@example.com")
        self.assertEqual(StaffMember.objects.count(), 1)

    def test_duplicate_email_of_inactive_member_allowed(self):
        m = add_staff_member(
            self.salon, "Dana", email="dana@example.com")
        m.active = False
        m.save(update_fields=["active"])
        add_staff_member(self.salon, "New Dana",
                         email="dana@example.com")
        self.assertEqual(StaffMember.objects.count(), 2)

    def test_pin_shape_refused(self):
        for bad in ("123", "123456789", "12a4", "12 34", True):
            with self.assertRaises(ValueError):
                add_staff_member(self.salon, "Dana", pin=bad)
        self.assertEqual(StaffMember.objects.count(), 0)

    def test_duplicate_pin_same_salon_refused_other_salon_allowed(self):
        add_staff_member(self.salon, "Dana", pin="1234")
        with self.assertRaises(ValueError):
            add_staff_member(self.salon, "Copy", pin="1234")
        add_staff_member(self.other, "Other", pin="1234")
        # Blank pins/emails are exempt from uniqueness.
        add_staff_member(self.salon, "A")
        add_staff_member(self.salon, "B", pin="", email="  ")
        self.assertEqual(StaffMember.objects.count(), 4)

    def test_validate_writes_nothing_and_returns_cleaned(self):
        cleaned = validate_add_staff_member(
            self.salon, "  Dana  ", staff_level=self.level,
            online_bookable=False, email=" dana@example.com ",
            pin="1234")
        self.assertEqual(StaffMember.objects.count(), 0)
        self.assertEqual(
            (cleaned["display_name"], cleaned["staff_level"],
             cleaned["online_bookable"], cleaned["email"],
             cleaned["pin"]),
            ("Dana", self.level, False, "dana@example.com", "1234"))

    def test_validate_same_errors_writes_nothing(self):
        add_staff_member(self.salon, "Existing",
                         email="dana@example.com", pin="1234")
        before = StaffMember.objects.count()
        for kwargs in ({"display_name": "  "},
                       {"display_name": "X",
                        "staff_level": self.other_level},
                       {"display_name": "X", "email": "bad"},
                       {"display_name": "X",
                        "email": "dana@example.com"},
                       {"display_name": "X", "pin": "12"},
                       {"display_name": "X", "pin": "1234"}):
            with self.assertRaises(ValueError):
                validate_add_staff_member(self.salon, **kwargs)
        self.assertEqual(StaffMember.objects.count(), before)
