import io

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from clients.models import Client
from saloncore.models import Salon


class AddClientCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")

    def run_cmd(self, **kwargs):
        out = io.StringIO()
        call_command("add_client", stdout=out, **kwargs)
        return out.getvalue()

    def test_happy_path_creates_client_opt_ins_off(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, first_name="Ada",
            last_name="Lovelace", email="ada@example.com",
            phone="555-0100")
        (c,) = Client.objects.all()
        self.assertEqual(
            (c.first_name, c.last_name, c.email, c.phone,
             c.sms_opt_in, c.email_opt_in, c.active),
            ("Ada", "Lovelace", "ada@example.com", "555-0100",
             False, False, True))
        self.assertIn("active=True", text)
        self.assertIn(f"Created client {c.pk}", text)
        self.assertIn(f"salon {self.salon.pk}", text)
        # Command output carries ids only, no contact details.
        self.assertNotIn("ada@example.com", text)
        self.assertNotIn("555-0100", text)

    def test_flag_form_sets_opt_ins_only_when_flagged(self):
        out = io.StringIO()
        call_command(
            "add_client", "--salon-id", str(self.salon.pk),
            "--first-name", "Ada", "--last-name", "Lovelace",
            "--sms-opt-in", stdout=out)
        (c,) = Client.objects.all()
        self.assertEqual((c.sms_opt_in, c.email_opt_in), (True, False))
        self.assertIn("sms_opt_in=True", out.getvalue())

    def test_flag_form_with_inactive_opt_ins_unaffected(self):
        out = io.StringIO()
        call_command(
            "add_client", "--salon-id", str(self.salon.pk),
            "--first-name", "Ada", "--last-name", "Lovelace",
            "--inactive", stdout=out)
        (c,) = Client.objects.all()
        self.assertEqual(
            (c.active, c.sms_opt_in, c.email_opt_in),
            (False, False, False))
        self.assertIn("active=False", out.getvalue())

    def test_call_command_inactive_kwarg(self):
        self.run_cmd(
            salon_id=self.salon.pk, first_name="Ada",
            last_name="Lovelace", inactive=True)
        (c,) = Client.objects.all()
        self.assertFalse(c.active)

    def test_call_command_opt_in_kwargs(self):
        self.run_cmd(
            salon_id=self.salon.pk, first_name="Ada",
            last_name="Lovelace", email_opt_in=True)
        (c,) = Client.objects.all()
        self.assertEqual((c.sms_opt_in, c.email_opt_in), (False, True))

    def test_dry_run_writes_nothing_and_previews(self):
        text = self.run_cmd(
            salon_id=self.salon.pk, first_name="Ada",
            last_name="Lovelace", email="ada@example.com",
            sms_opt_in=True, dry_run=True)
        self.assertEqual(Client.objects.count(), 0)
        self.assertIn("Dry run: would create client", text)
        self.assertIn("sms_opt_in=True", text)
        self.assertIn("no client written", text)

    def test_dry_run_with_inactive_writes_nothing(self):
        out = io.StringIO()
        call_command(
            "add_client", "--salon-id", str(self.salon.pk),
            "--first-name", "Ada", "--last-name", "Lovelace",
            "--inactive", "--dry-run", stdout=out)
        text = out.getvalue()
        self.assertEqual(Client.objects.count(), 0)
        self.assertIn("Dry run: would create client", text)
        self.assertIn("active=False", text)
        self.assertIn("sms_opt_in=False", text)
        self.assertIn("email_opt_in=False", text)
        self.assertIn("no client written", text)
        text = self.run_cmd(
            salon_id=self.salon.pk, first_name="Ada",
            last_name="Lovelace", inactive=True, dry_run=True)
        self.assertEqual(Client.objects.count(), 0)
        self.assertIn("active=False", text)

    def test_dry_run_invalid_writes_nothing(self):
        for kwargs in ({"first_name": " ", "last_name": "X"},
                       {"first_name": "X", "last_name": "Y",
                        "email": "nope"},
                       {"first_name": "X", "last_name": "Y",
                        "phone": "5" * 33}):
            with self.assertRaises(CommandError):
                self.run_cmd(
                    salon_id=self.salon.pk, dry_run=True, **kwargs)
        self.assertEqual(Client.objects.count(), 0)

    def test_unknown_salon_raises(self):
        with self.assertRaises(CommandError):
            self.run_cmd(salon_id=999999, first_name="X", last_name="Y")
        self.assertEqual(Client.objects.count(), 0)

    def test_blank_name_and_bad_email_raise(self):
        for kwargs in ({"first_name": " ", "last_name": "Y"},
                       {"first_name": "X", "last_name": ""},
                       {"first_name": "X", "last_name": "Y",
                        "email": "not-an-email"}):
            with self.assertRaises(CommandError):
                self.run_cmd(salon_id=self.salon.pk, **kwargs)
        self.assertEqual(Client.objects.count(), 0)
