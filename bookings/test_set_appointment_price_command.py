"""Tests for the set_appointment_price management command.

The command is a thin wrapper around
``bookings.price_override.set_appointment_price``: these
tests pin that a real run sets the override, that an empty
price clears it, that ``--dry-run`` writes nothing but prints
current -> override (with the service's validation still
applied), and that unknown salon/appointment, salon mismatch,
and invalid money surface as ``CommandError`` with the stored
override unchanged. Fixtures are tiny synthetic records --
unit logic only.
"""
import datetime
import io
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


class SetAppointmentPriceCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self.appointment = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, price_override=Decimal("80.00"),
            start=datetime.datetime.combine(DAY, datetime.time(9, 0), tzinfo=UTC),
            end=datetime.datetime.combine(DAY, datetime.time(9, 45), tzinfo=UTC))

    def _override(self):
        self.appointment.refresh_from_db()
        return self.appointment.price_override

    def test_real_run_sets_override_and_prints_current_to_new(self):
        out = io.StringIO()
        call_command(
            "set_appointment_price", appointment_id=self.appointment.pk,
            price="72.50", stdout=out)
        self.assertEqual(self._override(), Decimal("72.50"))
        text = out.getvalue()
        self.assertIn(str(self.appointment.pk), text)
        self.assertIn("80.00 -> 72.50", text)

    def test_real_run_string_args_and_salon_scoping(self):
        out = io.StringIO()
        call_command(
            "set_appointment_price", "--appointment-id",
            str(self.appointment.pk), "--salon-id", str(self.salon.pk),
            "--price", "65", stdout=out)
        self.assertEqual(self._override(), Decimal("65.00"))

    def test_empty_price_clears_override(self):
        out = io.StringIO()
        call_command(
            "set_appointment_price", appointment_id=self.appointment.pk,
            price="", stdout=out)
        self.assertIsNone(self._override())
        self.assertIn("80.00 -> none", out.getvalue())

    def test_empty_price_flag_form_clears_override(self):
        call_command(
            "set_appointment_price", "--appointment-id",
            str(self.appointment.pk), "--price", "", stdout=io.StringIO())
        self.assertIsNone(self._override())

    def test_dry_run_writes_nothing_but_prints_current_to_override(self):
        out = io.StringIO()
        call_command(
            "set_appointment_price", appointment_id=self.appointment.pk,
            price="72.50", dry_run=True, stdout=out)
        self.assertEqual(self._override(), Decimal("80.00"))
        text = out.getvalue()
        self.assertIn("Dry run", text)
        self.assertIn("80.00 -> 72.50", text)
        self.assertIn(str(self.appointment.pk), text)

    def test_dry_run_flag_form_and_clear_preview(self):
        out = io.StringIO()
        call_command(
            "set_appointment_price", "--appointment-id",
            str(self.appointment.pk), "--price", "", "--dry-run", stdout=out)
        self.assertEqual(self._override(), Decimal("80.00"))
        self.assertIn("Dry run", out.getvalue())
        self.assertIn("80.00 -> none", out.getvalue())

    def test_dry_run_then_real_run_still_sets(self):
        call_command(
            "set_appointment_price", appointment_id=self.appointment.pk,
            price="72.50", dry_run=True, stdout=io.StringIO())
        self.assertEqual(self._override(), Decimal("80.00"))
        call_command(
            "set_appointment_price", appointment_id=self.appointment.pk,
            price="72.50", stdout=io.StringIO())
        self.assertEqual(self._override(), Decimal("72.50"))

    def test_invalid_money_is_command_error_and_unchanged(self):
        for bad in ("abc", "-5", "NaN", "Infinity", "100000", "10.005"):
            with self.assertRaises(CommandError, msg=bad):
                call_command(
                    "set_appointment_price",
                    appointment_id=self.appointment.pk, price=bad,
                    stdout=io.StringIO())
            self.assertEqual(self._override(), Decimal("80.00"), bad)

    def test_dry_run_invalid_money_is_command_error_and_unchanged(self):
        with self.assertRaises(CommandError):
            call_command(
                "set_appointment_price", appointment_id=self.appointment.pk,
                price="-5", dry_run=True, stdout=io.StringIO())
        self.assertEqual(self._override(), Decimal("80.00"))

    def test_unknown_appointment_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "set_appointment_price", appointment_id=999999,
                price="72.50", stdout=io.StringIO())
        self.assertEqual(self._override(), Decimal("80.00"))

    def test_unknown_salon_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "set_appointment_price", appointment_id=self.appointment.pk,
                salon_id=999999, price="72.50", stdout=io.StringIO())
        self.assertEqual(self._override(), Decimal("80.00"))

    def test_appointment_outside_salon_is_command_error(self):
        other = Salon.objects.create(name="Other Salon", timezone="UTC")
        with self.assertRaises(CommandError):
            call_command(
                "set_appointment_price", appointment_id=self.appointment.pk,
                salon_id=other.pk, price="72.50", stdout=io.StringIO())
        self.assertEqual(self._override(), Decimal("80.00"))

    def test_dry_run_unknown_appointment_is_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "set_appointment_price", appointment_id=999999,
                price="72.50", dry_run=True, stdout=io.StringIO())
