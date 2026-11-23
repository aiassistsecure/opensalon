from decimal import Decimal

from django.test import TestCase, override_settings

from checkout.adapters import (
    AdapterNotConfigured,
    ChargeOutcome,
    PaymentAdapter,
    StoredCardData,
    charge_card_on_file,
    get_adapter,
    store_card,
)
from checkout.models import CardOnFile, DepositPolicy
from clients.models import Client
from saloncore.models import Salon


class FakeAdapter(PaymentAdapter):
    """An in-test adapter proving the seam wires through."""

    name = "fake"

    def save_card(self, salon, client, payment_token):
        return StoredCardData(
            provider_reference=f"ref-{payment_token}",
            brand="Testcard", last4="4242", exp_month=12, exp_year=2030,
        )

    def charge_saved_card(self, salon, card, amount, description=""):
        return ChargeOutcome(ok=True, provider_reference="ch_123")

    def charge_token(self, salon, payment_token, amount, description=""):
        return ChargeOutcome(ok=True, provider_reference="ch_456")

    def refund(self, salon, provider_reference, amount):
        return ChargeOutcome(ok=True, provider_reference=provider_reference)


FAKE = "checkout.test_payment_seam.FakeAdapter"


class PaymentSeamTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Guest")

    def test_no_setting_means_null_adapter_refuses(self):
        adapter = get_adapter()
        self.assertEqual(adapter.name, "none")
        with self.assertRaises(AdapterNotConfigured):
            adapter.charge_token(self.salon, "tok", Decimal("10.00"))

    @override_settings(OPENSALON_PAYMENT_ADAPTER=FAKE)
    def test_store_card_persists_only_reference_and_display_facts(self):
        card = store_card(self.salon, self.client, "tok_abc")
        self.assertEqual(card.provider_reference, "ref-tok_abc")
        self.assertEqual(card.brand, "Testcard")
        self.assertEqual(card.last4, "4242")
        self.assertEqual(card.exp_month, 12)
        self.assertTrue(card.active)

    @override_settings(OPENSALON_PAYMENT_ADAPTER=FAKE)
    def test_charge_card_on_file_goes_through_the_adapter(self):
        card = store_card(self.salon, self.client, "tok_abc")
        outcome = charge_card_on_file(card, Decimal("25.00"), "deposit")
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.provider_reference, "ch_123")

    @override_settings(OPENSALON_PAYMENT_ADAPTER=FAKE)
    def test_card_reference_unique_per_salon(self):
        store_card(self.salon, self.client, "tok_dup")
        with self.assertRaises(Exception):
            store_card(self.salon, self.client, "tok_dup")


class DepositPolicyTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")

    def _policy(self, kind, value="0"):
        return DepositPolicy.objects.create(
            salon=self.salon, kind=kind, value=Decimal(value))

    def test_none_is_zero(self):
        p = self._policy(DepositPolicy.Kind.NONE)
        self.assertEqual(p.deposit_due(Decimal("200.00")), Decimal("0.00"))

    def test_flat_is_capped_at_total(self):
        p = self._policy(DepositPolicy.Kind.FLAT, "50")
        self.assertEqual(p.deposit_due(Decimal("200.00")), Decimal("50.00"))
        self.assertEqual(p.deposit_due(Decimal("30.00")), Decimal("30.00"))

    def test_percent_rounds_to_cents(self):
        p = self._policy(DepositPolicy.Kind.PERCENT, "25")
        self.assertEqual(p.deposit_due(Decimal("200.00")), Decimal("50.00"))
        self.assertEqual(p.deposit_due(Decimal("99.99")), Decimal("25.00"))

    def test_full_prepay_is_the_total(self):
        p = self._policy(DepositPolicy.Kind.FULL_PREPAY)
        self.assertEqual(p.deposit_due(Decimal("123.45")), Decimal("123.45"))
