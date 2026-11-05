"""Per-client filter tests for the export_receipt command."""
import datetime
import io
import json
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Receipt, Sale, SaleItem
from checkout.receipt_export import EXPORT_FIELDNAMES, export_receipts
from checkout.receipts import build_receipt
from clients.models import Client
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)


def _aware(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour)))


def _service_text(salon, client=None):
    return json.dumps(
        export_receipts(DAY, DAY, salon=salon, client=client),
        indent=2) + "\n"


class ExportReceiptCommandClientFilterTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example",
            email="client@example.com")
        self.other_client = Client.objects.create(
            salon=self.salon, first_name="Other", last_name="Person")

    def _receipt(self, client="default", sent=False):
        sale = Sale.objects.create(
            salon=self.salon,
            client=self.client if client == "default" else client,
            status=Sale.Status.COMPLETED,
            completed_at=_aware(DAY))
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"))
        receipt = build_receipt(sale)
        updates = {"issued_at": _aware(DAY)}
        if sent:
            updates["recipient_email"] = "client@example.com"
            updates["sent_at"] = _aware(DAY, hour=13)
        Receipt.objects.filter(pk=receipt.pk).update(**updates)
        receipt.refresh_from_db()
        return receipt

    def test_client_id_filters_to_matching_receipts(self):
        own = self._receipt()
        self._receipt(client=self.other_client)
        self._receipt(client=None)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, client_id=self.client.pk,
            stdout=out)
        self.assertEqual(
            out.getvalue(), _service_text(self.salon, client=self.client))
        rows = json.loads(out.getvalue())
        self.assertEqual([r["id"] for r in rows], [own.pk])

    def test_client_id_via_cli_flag(self):
        self._receipt()
        other = self._receipt(client=self.other_client)
        out = io.StringIO()
        call_command(
            "export_receipt", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            "--client-id", str(self.other_client.pk), stdout=out)
        self.assertEqual(
            out.getvalue(),
            _service_text(self.salon, client=self.other_client))
        rows = json.loads(out.getvalue())
        self.assertEqual([r["id"] for r in rows], [other.pk])

    def test_client_id_composes_with_sale_and_delivery_status(self):
        sent = self._receipt(sent=True)
        self._receipt()
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, sale_id=sent.sale_id,
            client_id=self.other_client.pk, stdout=out)
        self.assertEqual(json.loads(out.getvalue()), [])
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, client_id=self.client.pk,
            delivery_status="sent", stdout=out)
        rows = json.loads(out.getvalue())
        self.assertEqual([r["id"] for r in rows], [sent.pk])

    def test_client_id_csv_format(self):
        self._receipt()
        self._receipt(client=self.other_client)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, format="csv",
            client_id=self.client.pk, stdout=out)
        lines = out.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], ",".join(EXPORT_FIELDNAMES))

    def test_no_client_id_is_all_clients_default(self):
        self._receipt()
        self._receipt(client=self.other_client)
        out = io.StringIO()
        call_command(
            "export_receipt", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), _service_text(self.salon))
        self.assertEqual(len(json.loads(out.getvalue())), 2)

    def test_unknown_client_id_raises_command_error(self):
        self._receipt()
        with self.assertRaises(CommandError):
            call_command(
                "export_receipt", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY,
                client_id=self.client.pk + 9999, stdout=io.StringIO())

    def test_other_salon_client_id_raises_command_error(self):
        other_salon = Salon.objects.create(name="Other Salon")
        theirs = Client.objects.create(
            salon=other_salon, first_name="Their", last_name="Client")
        with self.assertRaises(CommandError):
            call_command(
                "export_receipt", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, client_id=theirs.pk,
                stdout=io.StringIO())
