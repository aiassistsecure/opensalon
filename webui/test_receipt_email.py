"""Receipt emailing: the endpoint behind the modal button + POS.

The send is checkout.send_receipt's law — Django mail through the
salon's own settings, recipient defaulting to the client's email
on record, the receipt recording recipient + sent_at. Tests run on
Django's locmem backend, so mail.outbox is the proof.
"""
import json
from decimal import Decimal

from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from checkout.models import Sale, SaleItem
from checkout.receipts import build_receipt
from clients.models import Client as SalonClient
from saloncore.models import Salon


class ReceiptEmailTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(name="Mint", timezone="America/New_York")
        self.url = reverse("webui:daybook_receipt_email")
        self.guest = SalonClient.objects.create(
            salon=self.salon, first_name="Krystal",
            email="krystal@example.com",
        )
        self.sale = Sale.objects.create(
            salon=self.salon, client=self.guest,
            status=Sale.Status.COMPLETED, completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.SERVICE,
            description="Women's Haircut", quantity=1,
            unit_price=Decimal("65.00"),
        )
        self.receipt = build_receipt(self.sale)

    def post_json(self, payload):
        return self.client.post(
            self.url, data=json.dumps(payload),
            content_type="application/json",
        )

    def test_sends_to_the_client_on_record(self):
        response = self.post_json({"sale_id": self.sale.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sent_to"], "krystal@example.com")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["krystal@example.com"])
        self.receipt.refresh_from_db()
        self.assertIsNotNone(self.receipt.sent_at)
        self.assertEqual(self.receipt.recipient_email, "krystal@example.com")

    def test_typed_address_overrides(self):
        response = self.post_json(
            {"sale_id": self.sale.pk, "email": "other@example.com"}
        )
        self.assertEqual(response.json()["sent_to"], "other@example.com")
        self.assertEqual(mail.outbox[0].to, ["other@example.com"])

    def test_no_address_anywhere_is_a_clean_refusal(self):
        guest2 = SalonClient.objects.create(salon=self.salon, first_name="NoMail")
        sale2 = Sale.objects.create(
            salon=self.salon, client=guest2,
            status=Sale.Status.COMPLETED, completed_at=timezone.now(),
        )
        build_receipt(sale2)
        response = self.post_json({"sale_id": sale2.pk})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_pos_form_post_sends_and_redirects(self):
        response = self.client.post(
            self.url, {"web": "pos", "sale_id": str(self.sale.pk)}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
