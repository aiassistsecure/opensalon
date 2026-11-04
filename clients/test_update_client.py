from django.test import TestCase
from django.utils import timezone

from clients.models import Client
from clients.update_client import (
    ClientChange, update_client, validate_update_client,
)
from saloncore.models import Salon


def make(salon, first="Amy", last="Smith", **kw):
    return Client.objects.create(
        salon=salon, first_name=first, last_name=last, **kw)


class UpdateClientTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.client = make(
            self.salon, email="amy@example.com", phone="555-0101",
            external_id="ext-1", sms_opt_in=True)

    def fresh(self):
        return Client.objects.get(pk=self.client.pk)

    def test_updates_all_fields(self):
        result = update_client(
            self.salon, self.client, first_name="  Bea ",
            last_name="Jones", email="bea@example.com",
            phone="555-0202", active=False)
        fresh = self.fresh()
        self.assertEqual(
            (fresh.first_name, fresh.last_name, fresh.email,
             fresh.phone, fresh.active),
            ("Bea", "Jones", "bea@example.com", "555-0202", False))
        self.assertTrue(result.changed)
        self.assertEqual(
            result.changed_fields,
            ("first_name", "last_name", "email", "phone", "active"))
        self.assertEqual(
            result.changes[0],
            ClientChange("first_name", "Amy", "Bea"))
        self.assertIsNotNone(result.changed_at)
        self.assertTrue(timezone.is_aware(result.changed_at))

    def test_partial_update_leaves_omitted_fields_unchanged(self):
        result = update_client(self.salon, self.client, phone="555-9")
        fresh = self.fresh()
        self.assertEqual(
            (fresh.first_name, fresh.last_name, fresh.email,
             fresh.phone, fresh.active),
            ("Amy", "Smith", "amy@example.com", "555-9", True))
        self.assertEqual(result.changed_fields, ("phone",))

    def test_no_actual_change_saves_nothing(self):
        result = update_client(
            self.salon, self.client, first_name="Amy", active=True)
        self.assertFalse(result.changed)
        self.assertEqual(result.changed_fields, ())
        self.assertEqual(result.changes, ())
        self.assertIsNone(result.changed_at)

    def test_blank_email_and_phone_clear_contact_fields(self):
        update_client(self.salon, self.client, email="", phone="  ")
        fresh = self.fresh()
        self.assertEqual((fresh.email, fresh.phone), ("", ""))

    def test_opt_ins_and_other_fields_never_change(self):
        before = self.fresh()
        update_client(
            self.salon, self.client, first_name="Bea", active=False)
        after = self.fresh()
        self.assertTrue(after.sms_opt_in)
        self.assertFalse(after.email_opt_in)
        for field in ("salon_id", "external_id", "created_at", "payload"):
            self.assertEqual(
                getattr(after, field), getattr(before, field), field)

    def test_opt_in_kwargs_are_rejected(self):
        with self.assertRaises(TypeError):
            update_client(self.salon, self.client, sms_opt_in=False)

    def test_unsaved_unrelated_edits_are_not_written(self):
        self.client.email = "sneaky@example.com"
        update_client(self.salon, self.client, first_name="Bea")
        fresh = self.fresh()
        self.assertEqual(fresh.first_name, "Bea")
        self.assertEqual(fresh.email, "amy@example.com")

    def test_neither_field_given_rejected(self):
        with self.assertRaises(ValueError):
            update_client(self.salon, self.client)
        with self.assertRaises(ValueError):
            validate_update_client(self.salon, self.client)

    def test_invalid_values_rejected_and_unchanged(self):
        bad_calls = (
            {"first_name": " "}, {"first_name": "x" * 81},
            {"last_name": ""}, {"last_name": 123},
            {"email": "not-an-email"},
            {"email": "a" * 243 + "@example.com"},
            {"email": 123}, {"phone": "5" * 33},
            {"active": "true"}, {"active": 1},
        )
        for kwargs in bad_calls:
            with self.assertRaises(ValueError, msg=repr(kwargs)):
                update_client(self.salon, self.client, **kwargs)
        fresh = self.fresh()
        self.assertEqual(
            (fresh.first_name, fresh.last_name, fresh.email,
             fresh.phone, fresh.active),
            ("Amy", "Smith", "amy@example.com", "555-0101", True))

    def test_cross_salon_and_unsaved_rejected(self):
        other_client = make(self.other, "Bob", "Adams")
        with self.assertRaises(ValueError):
            update_client(self.salon, other_client, first_name="X")
        with self.assertRaises(ValueError):
            update_client(self.other, self.client, first_name="X")
        with self.assertRaises(ValueError):
            update_client(
                Salon(name="Unsaved"), self.client, first_name="X")
        with self.assertRaises(ValueError):
            update_client(
                self.salon, Client(salon=self.salon), first_name="X")
        with self.assertRaises(ValueError):
            update_client(None, self.client, first_name="X")
        with self.assertRaises(ValueError):
            update_client(self.salon, None, first_name="X")
        self.assertEqual(self.fresh().first_name, "Amy")

    def test_fields_are_keyword_only(self):
        with self.assertRaises(TypeError):
            update_client(self.salon, self.client, "Bea")

    def test_validate_writes_nothing_and_returns_only_given(self):
        cleaned = validate_update_client(
            self.salon, self.client, first_name=" Bea ", active=False)
        self.assertEqual(self.fresh().first_name, "Amy")
        self.assertTrue(self.fresh().active)
        self.assertEqual(cleaned["first_name"], "Bea")
        self.assertEqual(cleaned["active"], False)
        self.assertIs(cleaned["client"], self.client)
        self.assertIs(cleaned["salon"], self.salon)
        for omitted in ("last_name", "email", "phone"):
            self.assertNotIn(omitted, cleaned)

    def test_validate_same_errors_write_nothing(self):
        for kwargs in ({"email": "nope"}, {"active": "yes"},
                       {"phone": "5" * 33}):
            with self.assertRaises(ValueError):
                validate_update_client(self.salon, self.client, **kwargs)
        self.assertEqual(self.fresh().email, "amy@example.com")
