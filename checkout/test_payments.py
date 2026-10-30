from decimal import Decimal

from django.test import TestCase

from checkout.models import Payment, Sale
from checkout.payments import (
    CashProvider,
    ExternalTenderProvider,
    PaymentProvider,
    PaymentResult,
)
from saloncore.models import Salon


class PaymentProviderContractTests(TestCase):
    def test_abstract_provider_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            PaymentProvider()

    def test_incomplete_subclass_cannot_be_instantiated(self):
        class Partial(PaymentProvider):
            def charge(self, amount, reference=""):
                return super().charge(amount, reference)

        with self.assertRaises(TypeError):
            Partial()

    def test_result_is_dataclass_with_defaults(self):
        result = PaymentResult(
            success=True, status="completed", amount=Decimal("10.00")
        )
        self.assertEqual(result.reference, "")
        self.assertEqual(result.message, "")


class BuiltInProviderTests(TestCase):
    def _check_charge_and_refund(self, provider, name):
        result = provider.charge(Decimal("42.50"), reference="sale-1")
        self.assertIsInstance(result, PaymentResult)
        self.assertTrue(result.success)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.amount, Decimal("42.50"))
        self.assertEqual(result.reference, "sale-1")

        auto = provider.charge(Decimal("5.00"))
        self.assertTrue(auto.reference.startswith(f"{name}-"))

        class Stub:
            provider_reference = "sale-1"

        refund = provider.refund(Stub(), Decimal("10.00"))
        self.assertTrue(refund.success)
        self.assertEqual(refund.status, "refunded")
        self.assertEqual(refund.amount, Decimal("10.00"))
        self.assertEqual(refund.reference, "sale-1")

        with self.assertRaises(ValueError):
            provider.charge(Decimal("0"))
        with self.assertRaises(ValueError):
            provider.charge(Decimal("-1.00"))
        with self.assertRaises(ValueError):
            provider.refund(Stub(), Decimal("0"))

    def test_cash_provider(self):
        provider = CashProvider()
        self.assertEqual(provider.name, "cash")
        self._check_charge_and_refund(provider, "cash")

    def test_external_tender_provider(self):
        provider = ExternalTenderProvider()
        self.assertEqual(provider.name, "external")
        self._check_charge_and_refund(provider, "external")


class PaymentModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        self.sale = Sale.objects.create(salon=self.salon)

    def test_creation_defaults_and_fk(self):
        payment = Payment.objects.create(
            sale=self.sale, amount=Decimal("85.00")
        )
        payment.refresh_from_db()
        self.assertEqual(payment.sale, self.sale)
        self.assertIn(payment, list(self.sale.payments.all()))
        self.assertEqual(payment.method, Payment.Method.CASH)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.provider_reference, "")
        self.assertIsNotNone(payment.created_at)
        self.assertIsNotNone(payment.updated_at)

    def test_method_and_status_choices(self):
        self.assertEqual(
            [c[0] for c in Payment.Method.choices], ["cash", "external"]
        )
        self.assertEqual(
            [c[0] for c in Payment.Status.choices],
            ["pending", "completed", "failed", "refunded"],
        )

    def test_record_completed_charge_from_provider_result(self):
        result = CashProvider().charge(self.sale.total or Decimal("20.00"),
                                        reference="till-7")
        payment = Payment.objects.create(
            sale=self.sale, method=Payment.Method.CASH,
            amount=result.amount, status=result.status,
            provider_reference=result.reference,
        )
        self.assertEqual(payment.status, "completed")
        self.assertEqual(payment.provider_reference, "till-7")
        self.assertIn("Cash", str(payment))

    def test_payments_cascade_on_sale_delete(self):
        Payment.objects.create(sale=self.sale, amount=Decimal("1.00"))
        self.sale.delete()
        self.assertEqual(Payment.objects.count(), 0)
