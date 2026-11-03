"""Tests for the bookings.price_override.set_appointment_price service.

Pins that a valid call sets ``price_override`` cent-quantized
(leaving the price-book row untouched), that empty input
(``None``, ``""``, whitespace) CLEARS the override, and that
invalid money -- non-numeric, non-finite, negative, too
large, or sub-cent -- raises ``ValidationError`` writing
nothing. Fixtures are tiny synthetic records -- unit logic
only.
"""
import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from bookings.models import Appointment
from bookings.price_override import (
    set_appointment_price, validate_set_appointment_price)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
UTC = datetime.timezone.utc


class SetAppointmentPriceServiceTests(TestCase):
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
            service=self.service,
            start=datetime.datetime.combine(DAY, datetime.time(9, 0), tzinfo=UTC),
            end=datetime.datetime.combine(DAY, datetime.time(9, 45), tzinfo=UTC))

    def _override(self):
        self.appointment.refresh_from_db()
        return self.appointment.price_override

    def test_sets_override_cent_quantized(self):
        result = set_appointment_price(self.appointment, "72.5")
        self.assertEqual(result.price_override, Decimal("72.50"))
        self.assertEqual(self._override(), Decimal("72.50"))
        # The price-book row is never touched.
        self.service.refresh_from_db()
        self.assertEqual(self.service.name, "Haircut")
        self.assertEqual(self.service.service_minutes, 45)

    def test_sets_from_decimal_and_int_and_zero(self):
        set_appointment_price(self.appointment, Decimal("88.00"))
        self.assertEqual(self._override(), Decimal("88.00"))
        set_appointment_price(self.appointment, 0)
        self.assertEqual(self._override(), Decimal("0.00"))

    def test_validate_set_appointment_price_writes_nothing(self):
        before = self.appointment.updated_at
        self.assertEqual(
            validate_set_appointment_price(self.appointment, "72.5"),
            Decimal("72.50"))
        self.assertIsNone(
            validate_set_appointment_price(self.appointment, ""))
        self.appointment.refresh_from_db()
        self.assertIsNone(self.appointment.price_override)
        self.assertEqual(self.appointment.updated_at, before)
        with self.assertRaises(ValidationError):
            validate_set_appointment_price(self.appointment, "-5")
        self.assertIsNone(self._override())

    def test_price_kwarg_alias(self):
        set_appointment_price(self.appointment, price="65.25")
        self.assertEqual(self._override(), Decimal("65.25"))

    def test_empty_input_clears_override(self):
        for empty in (None, "", "   "):
            set_appointment_price(self.appointment, "72.50")
            self.assertEqual(self._override(), Decimal("72.50"))
            set_appointment_price(self.appointment, empty)
            self.assertIsNone(self._override())

    def test_invalid_money_writes_nothing(self):
        set_appointment_price(self.appointment, "72.50")
        for bad in ("abc", "-5", Decimal("-0.01"), "NaN", "Infinity",
                    "-Infinity", Decimal("NaN"), Decimal("Infinity"),
                    "100000", "99999.991", "10.005", "0.001",
                    Decimal("1.234")):
            with self.assertRaises(ValidationError, msg=str(bad)):
                set_appointment_price(self.appointment, bad)
            self.assertEqual(self._override(), Decimal("72.50"), str(bad))

    def test_error_messages_match_the_view_verbatim(self):
        cases = (
            ("abc", "price is not a number"),
            ("NaN", "price is not a number"),
            ("-5", "price cannot be negative"),
            ("100000", "price is too large"),
        )
        for raw, message in cases:
            with self.assertRaises(ValidationError) as ctx:
                set_appointment_price(self.appointment, raw)
            self.assertIn(message, ctx.exception.messages)

    def test_missing_or_unknown_appointment_writes_nothing(self):
        with self.assertRaises(ValidationError):
            set_appointment_price(None, "72.50")
        unsaved = Appointment(
            client=self.client, staff_member=self.staff,
            service=self.service,
            start=datetime.datetime.combine(DAY, datetime.time(11, 0), tzinfo=UTC),
            end=datetime.datetime.combine(DAY, datetime.time(11, 45), tzinfo=UTC))
        with self.assertRaises(ValidationError):
            set_appointment_price(unsaved, "72.50")
        ghost = Appointment(pk=999999)
        with self.assertRaises(ValidationError):
            set_appointment_price(ghost, "72.50")
        self.assertIsNone(self._override())
