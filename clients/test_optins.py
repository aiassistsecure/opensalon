from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from clients.models import Client
from clients.optins import OptInChange, update_client_opt_ins
from saloncore.models import Salon


def make(salon, first="Amy", last="Smith", **kw):
    return Client.objects.create(
        salon=salon, first_name=first, last_name=last, **kw
    )


class UpdateClientOptInsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.other = Salon.objects.create(name="Other Salon")
        self.client = make(
            self.salon, email="amy@example.com", phone="555-0101",
            external_id="ext-1",
        )

    def fresh(self):
        return Client.objects.get(pk=self.client.pk)

    def test_opt_in_both_channels(self):
        result = update_client_opt_ins(
            self.salon, self.client, sms_opt_in=True, email_opt_in=True
        )
        fresh = self.fresh()
        self.assertTrue(fresh.sms_opt_in)
        self.assertTrue(fresh.email_opt_in)
        self.assertTrue(result.changed)
        self.assertEqual(result.changed_fields, ("sms_opt_in", "email_opt_in"))
        self.assertEqual(
            result.changes,
            (OptInChange("sms_opt_in", False, True),
             OptInChange("email_opt_in", False, True)),
        )
        self.assertTrue(result.sms_opt_in)
        self.assertTrue(result.email_opt_in)
        self.assertIsNotNone(result.changed_at)
        self.assertTrue(timezone.is_aware(result.changed_at))

    def test_opt_out_both_channels(self):
        self.client.sms_opt_in = True
        self.client.email_opt_in = True
        self.client.save()
        result = update_client_opt_ins(
            self.salon, self.client, sms_opt_in=False, email_opt_in=False
        )
        fresh = self.fresh()
        self.assertFalse(fresh.sms_opt_in)
        self.assertFalse(fresh.email_opt_in)
        self.assertEqual(
            result.changes,
            (OptInChange("sms_opt_in", True, False),
             OptInChange("email_opt_in", True, False)),
        )

    def test_partial_update_leaves_other_flag_unchanged(self):
        self.client.email_opt_in = True
        self.client.save()
        result = update_client_opt_ins(
            self.salon, self.client, sms_opt_in=True
        )
        fresh = self.fresh()
        self.assertTrue(fresh.sms_opt_in)
        self.assertTrue(fresh.email_opt_in)  # untouched, was already True
        self.assertEqual(result.changed_fields, ("sms_opt_in",))

    def test_channels_are_independent(self):
        update_client_opt_ins(self.salon, self.client, email_opt_in=True)
        fresh = self.fresh()
        self.assertTrue(fresh.email_opt_in)
        self.assertFalse(fresh.sms_opt_in)

    def test_no_actual_change_saves_nothing_and_reports_no_timestamp(self):
        result = update_client_opt_ins(
            self.salon, self.client, sms_opt_in=False, email_opt_in=False
        )
        self.assertFalse(result.changed)
        self.assertEqual(result.changed_fields, ())
        self.assertEqual(result.changes, ())
        self.assertIsNone(result.changed_at)
        self.assertFalse(self.fresh().sms_opt_in)

    def test_only_differing_flag_is_reported_changed(self):
        result = update_client_opt_ins(
            self.salon, self.client, sms_opt_in=False, email_opt_in=True
        )
        self.assertEqual(result.changed_fields, ("email_opt_in",))
        self.assertIsNotNone(result.changed_at)

    def test_no_other_fields_changed(self):
        before = self.fresh()
        update_client_opt_ins(
            self.salon, self.client, sms_opt_in=True, email_opt_in=True
        )
        after = self.fresh()
        for field in ("salon_id", "external_id", "first_name", "last_name",
                      "email", "phone", "active", "created_at"):
            self.assertEqual(getattr(after, field), getattr(before, field), field)

    def test_unsaved_unrelated_edits_are_not_written(self):
        # update_fields must keep an unrelated in-memory edit out of the DB.
        self.client.first_name = "Changed"
        update_client_opt_ins(self.salon, self.client, sms_opt_in=True)
        self.assertEqual(self.fresh().first_name, "Amy")
        self.assertTrue(self.fresh().sms_opt_in)

    def test_cross_salon_client_rejected_and_unchanged(self):
        other_client = make(self.other, "Bob", "Adams")
        with self.assertRaises(ValidationError):
            update_client_opt_ins(
                self.salon, other_client, sms_opt_in=True
            )
        other_client.refresh_from_db()
        self.assertFalse(other_client.sms_opt_in)

    def test_salon_argument_must_match_client_salon(self):
        with self.assertRaises(ValidationError):
            update_client_opt_ins(self.other, self.client, sms_opt_in=True)
        self.assertFalse(self.fresh().sms_opt_in)

    def test_neither_flag_given_rejected(self):
        with self.assertRaises(ValidationError):
            update_client_opt_ins(self.salon, self.client)
        self.assertFalse(self.fresh().sms_opt_in)
        self.assertFalse(self.fresh().email_opt_in)

    def test_non_boolean_values_rejected_and_unchanged(self):
        for bad in ("true", "false", 1, 0, [], object()):
            with self.assertRaises(ValidationError, msg=repr(bad)):
                update_client_opt_ins(
                    self.salon, self.client, sms_opt_in=bad
                )
            with self.assertRaises(ValidationError, msg=repr(bad)):
                update_client_opt_ins(
                    self.salon, self.client, email_opt_in=bad
                )
        self.assertFalse(self.fresh().sms_opt_in)
        self.assertFalse(self.fresh().email_opt_in)

    def test_unsaved_or_wrong_type_arguments_rejected(self):
        with self.assertRaises(ValidationError):
            update_client_opt_ins(
                self.salon, Client(salon=self.salon), sms_opt_in=True
            )
        with self.assertRaises(ValidationError):
            update_client_opt_ins(
                Salon(name="Unsaved"), self.client, sms_opt_in=True
            )
        with self.assertRaises(ValidationError):
            update_client_opt_ins(None, self.client, sms_opt_in=True)
        with self.assertRaises(ValidationError):
            update_client_opt_ins(self.salon, None, sms_opt_in=True)

    def test_flags_are_keyword_only(self):
        with self.assertRaises(TypeError):
            update_client_opt_ins(self.salon, self.client, True)
