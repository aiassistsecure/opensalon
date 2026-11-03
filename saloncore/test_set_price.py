"""Tests for the saloncore.pricing set_price service + command."""
import io
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import CommandError, call_command
from django.test import TestCase

from saloncore.models import (
    PriceChange, Salon, Service, ServiceCategory, ServicePrice, StaffLevel,
)
from saloncore.pricing import set_price


class SetPriceBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Price Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=self.category, name="Haircut", service_minutes=60)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Senior")

    def make_price(self, amount="50.00", **kw):
        return ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal(amount), **kw)


class SetPriceServiceTests(SetPriceBase):
    def test_creates_price_without_audit_row(self):
        result = set_price(self.service, self.level, Decimal("85.00"),
                           is_from=True, changed_by="set_price")
        self.assertTrue(result.created)
        self.assertIsNone(result.old_amount)
        self.assertIsNone(result.change)
        self.assertEqual(result.price.amount, Decimal("85.00"))
        self.assertTrue(result.price.is_from)
        self.assertTrue(result.price.active)
        self.assertEqual(PriceChange.objects.count(), 0)

    def test_update_appends_audit_with_caller_changed_by(self):
        self.make_price("50.00")
        result = set_price(self.service, self.level, "60.00",
                           changed_by="set_price", note="Manual rise")
        self.assertFalse(result.created)
        self.assertEqual(result.old_amount, Decimal("50.00"))
        self.assertEqual(result.price.amount, Decimal("60.00"))
        change = PriceChange.objects.get(service_price=result.price)
        self.assertEqual(result.change.pk, change.pk)
        self.assertEqual(change.changed_by, "set_price")
        self.assertEqual(change.old_amount, Decimal("50.00"))
        self.assertEqual(change.new_amount, Decimal("60.00"))
        self.assertEqual(change.note, "Manual rise")

    def test_unchanged_amount_appends_no_audit(self):
        self.make_price("50.00")
        result = set_price(self.service, self.level, Decimal("50.00"),
                           is_from=True, changed_by="set_price")
        self.assertIsNone(result.change)
        self.assertEqual(PriceChange.objects.count(), 0)
        self.assertTrue(result.price.is_from)  # flag still updates

    def test_is_from_none_leaves_stored_flag(self):
        self.make_price("50.00", is_from=True)
        result = set_price(self.service, self.level, Decimal("55.00"),
                           changed_by="import_price_book")
        self.assertTrue(result.price.is_from)
        self.assertEqual(
            PriceChange.objects.get().changed_by, "import_price_book")

    def test_cross_salon_level_refused_writes_nothing(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = StaffLevel.objects.create(salon=other, name="Foreign")
        with self.assertRaises(ValidationError):
            set_price(self.service, foreign, Decimal("10.00"),
                      changed_by="set_price")
        self.assertEqual(ServicePrice.objects.count(), 0)
        self.assertEqual(PriceChange.objects.count(), 0)

    def test_invalid_amount_refused_writes_nothing(self):
        with self.assertRaises(ValidationError):
            set_price(self.service, self.level, "not-a-price",
                      changed_by="set_price")
        self.assertEqual(ServicePrice.objects.count(), 0)

    def test_unsaved_service_refused(self):
        unsaved = Service(category=self.category, name="Ghost",
                          service_minutes=30)
        with self.assertRaises(ValidationError):
            set_price(unsaved, self.level, Decimal("10.00"))


class SetPriceCommandTests(SetPriceBase):
    def run_command(self, **kwargs):
        out = io.StringIO()
        call_command("set_price", stdout=out, **kwargs)
        return out.getvalue()

    def base_kwargs(self, **over):
        kwargs = {"service_id": self.service.pk,
                  "staff_level_id": self.level.pk, "amount": "85.00"}
        kwargs.update(over)
        return kwargs

    def test_command_creates_price(self):
        out = self.run_command(**self.base_kwargs(is_from="true"))
        price = ServicePrice.objects.get(
            service=self.service, staff_level=self.level)
        self.assertEqual(price.amount, Decimal("85.00"))
        self.assertTrue(price.is_from)
        self.assertIn("None -> 85.00", out)
        self.assertEqual(PriceChange.objects.count(), 0)

    def test_command_update_audits_as_set_price(self):
        self.make_price("50.00")
        out = self.run_command(**self.base_kwargs(amount="65.00"))
        self.assertIn("50.00 -> 65.00", out)
        change = PriceChange.objects.get()
        self.assertEqual(change.changed_by, "set_price")
        self.assertEqual(change.old_amount, Decimal("50.00"))
        self.assertEqual(change.new_amount, Decimal("65.00"))

    def test_command_dry_run_writes_nothing(self):
        self.make_price("50.00")
        out = self.run_command(**self.base_kwargs(
            amount="65.00", dry_run=True))
        self.assertIn("50.00 -> 65.00", out)
        self.assertIn("Dry run", out)
        price = ServicePrice.objects.get(
            service=self.service, staff_level=self.level)
        self.assertEqual(price.amount, Decimal("50.00"))
        self.assertEqual(PriceChange.objects.count(), 0)

    def test_command_dry_run_create_writes_nothing(self):
        out = self.run_command(**self.base_kwargs(dry_run=True))
        self.assertIn("None -> 85.00", out)
        self.assertEqual(ServicePrice.objects.count(), 0)
        self.assertEqual(PriceChange.objects.count(), 0)

    def test_command_unknown_service(self):
        with self.assertRaises(CommandError):
            self.run_command(**self.base_kwargs(service_id=999999))

    def test_command_unknown_level(self):
        with self.assertRaises(CommandError):
            self.run_command(**self.base_kwargs(staff_level_id=999999))

    def test_command_cross_salon_level(self):
        other = Salon.objects.create(name="Other Salon")
        foreign = StaffLevel.objects.create(salon=other, name="Foreign")
        with self.assertRaises(CommandError):
            self.run_command(**self.base_kwargs(
                staff_level_id=foreign.pk))
        self.assertEqual(ServicePrice.objects.count(), 0)

    def test_command_invalid_amount(self):
        with self.assertRaises(CommandError):
            self.run_command(**self.base_kwargs(amount="junk"))
        self.assertEqual(ServicePrice.objects.count(), 0)

    def test_command_creates_inactive_price(self):
        self.run_command(**self.base_kwargs(price_active="false"))
        price = ServicePrice.objects.get(
            service=self.service, staff_level=self.level)
        self.assertEqual(price.amount, Decimal("85.00"))
        self.assertFalse(price.active)

    def test_command_price_active_true_reactivates_price(self):
        self.make_price("50.00", active=False)
        self.run_command(**self.base_kwargs(price_active="true"))
        price = ServicePrice.objects.get(
            service=self.service, staff_level=self.level)
        self.assertTrue(price.active)

    def test_command_price_active_false_deactivates_price(self):
        self.make_price("50.00", active=True)
        self.run_command(**self.base_kwargs(price_active="false"))
        price = ServicePrice.objects.get(
            service=self.service, staff_level=self.level)
        self.assertFalse(price.active)

    def test_command_omitted_price_active_passes_none_default(self):
        # Omitted = today's behaviour: the service receives None,
        # which it defines as active -- even on an inactive row.
        self.make_price("50.00", active=False)
        self.run_command(**self.base_kwargs())
        price = ServicePrice.objects.get(
            service=self.service, staff_level=self.level)
        self.assertTrue(price.active)

    def test_command_dry_run_shows_price_active_writes_nothing(self):
        self.make_price("50.00", active=True)
        out = self.run_command(**self.base_kwargs(
            amount="65.00", price_active="false", dry_run=True))
        self.assertIn("price_active=False", out)
        self.assertIn("Dry run", out)
        price = ServicePrice.objects.get(
            service=self.service, staff_level=self.level)
        self.assertEqual(price.amount, Decimal("50.00"))
        self.assertTrue(price.active)
        self.assertEqual(PriceChange.objects.count(), 0)

    def test_command_dry_run_omitted_shows_price_active_none(self):
        out = self.run_command(**self.base_kwargs(dry_run=True))
        self.assertIn("price_active=None", out)
        self.assertEqual(ServicePrice.objects.count(), 0)

    def test_command_invalid_price_active(self):
        with self.assertRaises(CommandError):
            self.run_command(**self.base_kwargs(price_active="junk"))
        self.assertEqual(ServicePrice.objects.count(), 0)
