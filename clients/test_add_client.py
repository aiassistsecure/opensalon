from django.test import TestCase

from clients.add_client import add_client, validate_add_client
from clients.models import Client
from saloncore.models import Salon


class AddClientTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")

    def test_creates_client_with_all_fields(self):
        c = add_client(
            self.salon, "  Ada  ", " Lovelace ",
            email="ada@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(
            (c.salon, c.first_name, c.last_name, c.email, c.phone,
             c.sms_opt_in, c.email_opt_in, c.external_id, c.active),
            (self.salon, "Ada", "Lovelace", "ada@example.com",
             "555-0100", True, True, "", True))

    def test_defaults_blank_contact_and_opt_ins_false(self):
        c = add_client(self.salon, "Ada", "Lovelace")
        self.assertEqual(
            (c.email, c.phone, c.sms_opt_in, c.email_opt_in, c.active),
            ("", "", False, False, True))

    def test_inactive_client_opt_ins_unaffected(self):
        c = add_client(self.salon, "Ada", "Lovelace", active=False)
        self.assertEqual(
            (c.active, c.sms_opt_in, c.email_opt_in),
            (False, False, False))
        flagged = add_client(
            self.salon, "B", "Two", active=False, sms_opt_in=True)
        self.assertEqual(
            (flagged.active, flagged.sms_opt_in, flagged.email_opt_in),
            (False, True, False))

    def test_non_bool_active_refused(self):
        for kwargs in ({"active": "yes"}, {"active": 1},
                       {"active": None}):
            with self.assertRaises(ValueError):
                add_client(self.salon, "A", "One", **kwargs)
            with self.assertRaises(ValueError):
                validate_add_client(self.salon, "A", "One", **kwargs)
        self.assertEqual(Client.objects.count(), 0)

    def test_opt_ins_set_independently_only_when_explicit(self):
        sms_only = add_client(self.salon, "A", "One", sms_opt_in=True)
        email_only = add_client(self.salon, "B", "Two", email_opt_in=True)
        self.assertEqual(
            (sms_only.sms_opt_in, sms_only.email_opt_in), (True, False))
        self.assertEqual(
            (email_only.sms_opt_in, email_only.email_opt_in), (False, True))

    def test_duplicate_email_and_phone_allowed(self):
        add_client(self.salon, "A", "One", email="a@example.com",
                   phone="555-0100")
        add_client(self.salon, "B", "Two", email="a@example.com",
                   phone="555-0100")
        add_client(self.other, "C", "Three", email="a@example.com")
        self.assertEqual(Client.objects.count(), 3)

    def test_blank_names_refused(self):
        for kwargs in ({"first_name": "", "last_name": "X"},
                       {"first_name": "   ", "last_name": "X"},
                       {"first_name": "X", "last_name": ""},
                       {"first_name": None, "last_name": "X"},
                       {"first_name": "X", "last_name": 123}):
            with self.assertRaises(ValueError):
                add_client(self.salon, **kwargs)
        self.assertEqual(Client.objects.count(), 0)

    def test_overlong_fields_refused_not_truncated(self):
        for kwargs in ({"first_name": "x" * 81, "last_name": "X"},
                       {"first_name": "X", "last_name": "x" * 81},
                       {"first_name": "X", "last_name": "Y",
                        "email": "a" * 243 + "@example.com"},
                       {"first_name": "X", "last_name": "Y",
                        "phone": "5" * 33}):
            with self.assertRaises(ValueError):
                add_client(self.salon, **kwargs)
        self.assertEqual(Client.objects.count(), 0)

    def test_invalid_email_refused_blank_email_allowed(self):
        for bad in ("not-an-email", "a@", "@example.com", 123):
            with self.assertRaises(ValueError):
                add_client(self.salon, "A", "One", email=bad)
        add_client(self.salon, "A", "One", email="  ")
        self.assertEqual(Client.objects.count(), 1)

    def test_unsaved_salon_refused(self):
        with self.assertRaises(ValueError):
            add_client(Salon(name="Unsaved"), "A", "One")
        self.assertEqual(Client.objects.count(), 0)

    def test_non_bool_opt_ins_refused(self):
        for kwargs in ({"sms_opt_in": "yes"}, {"email_opt_in": 1},
                       {"sms_opt_in": None}):
            with self.assertRaises(ValueError):
                add_client(self.salon, "A", "One", **kwargs)
        self.assertEqual(Client.objects.count(), 0)

    def test_validate_add_client_writes_nothing(self):
        cleaned = validate_add_client(
            self.salon, "  Ada ", " Lovelace",
            email="ada@example.com", phone="555-0100",
            email_opt_in=True)
        self.assertEqual(Client.objects.count(), 0)
        self.assertEqual(
            (cleaned["first_name"], cleaned["last_name"],
             cleaned["email"], cleaned["phone"],
             cleaned["sms_opt_in"], cleaned["email_opt_in"],
             cleaned["active"]),
            ("Ada", "Lovelace", "ada@example.com", "555-0100",
             False, True, True))
        inactive = validate_add_client(
            self.salon, "Ada", "Lovelace", active=False)
        self.assertFalse(inactive["active"])
        self.assertEqual(Client.objects.count(), 0)

    def test_validate_add_client_same_errors_writes_nothing(self):
        for kwargs in ({"first_name": " ", "last_name": "X"},
                       {"first_name": "X", "last_name": "x" * 81},
                       {"first_name": "X", "last_name": "Y",
                        "email": "nope"},
                       {"first_name": "X", "last_name": "Y",
                        "sms_opt_in": "yes"}):
            with self.assertRaises(ValueError):
                validate_add_client(self.salon, **kwargs)
        self.assertEqual(Client.objects.count(), 0)
