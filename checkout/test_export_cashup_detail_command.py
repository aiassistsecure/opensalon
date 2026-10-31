import datetime
import io
import os
import tempfile
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from checkout.cashup_detail import cashup_detail
from checkout.cashup_detail_export import export_cashup_detail_csv
from checkout.models import Payment, Sale, SaleItem
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


class ExportCashupDetailCommandTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon")
        sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale, kind="service", description="Haircut",
            unit_price=Decimal("85.00"),
        )
        payment = Payment.objects.create(
            sale=sale, method="cash", amount=Decimal("85.00"),
            status=Payment.Status.COMPLETED,
        )
        stamp = timezone.make_aware(
            datetime.datetime.combine(DAY, datetime.time(12, 0)))
        Payment.objects.filter(pk=payment.pk).update(created_at=stamp)
        Sale.objects.filter(pk=sale.pk).update(created_at=stamp)

    def test_stdout_matches_service(self):
        out = io.StringIO()
        call_command(
            "export_cashup_detail", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_cashup_detail_csv(self.salon, DAY, DAY))

    def test_stdout_matches_service_with_string_date_args(self):
        out = io.StringIO()
        call_command(
            "export_cashup_detail", "--salon-id", str(self.salon.pk),
            "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
            stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_cashup_detail_csv(self.salon, DAY, DAY))

    def test_output_file_matches_service(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "cashup_detail.csv")
            call_command(
                "export_cashup_detail", salon_id=self.salon.pk,
                start_date=DAY, end_date=NEXT, output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(
            written, export_cashup_detail_csv(self.salon, DAY, NEXT))
        self.assertEqual(out.getvalue(), "")

    def test_delegates_to_service_verbatim(self):
        with mock.patch(
            "checkout.management.commands.export_cashup_detail"
            ".export_cashup_detail_csv",
            wraps=export_cashup_detail_csv,
        ) as spy:
            call_command(
                "export_cashup_detail", salon_id=self.salon.pk,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())
        spy.assert_called_once_with(self.salon, DAY, DAY)

    def test_unknown_salon_raises_command_error(self):
        with self.assertRaises(CommandError):
            call_command(
                "export_cashup_detail", salon_id=self.salon.pk + 999,
                start_date=DAY, end_date=DAY, stdout=io.StringIO())

    def test_service_errors_propagate(self):
        with self.assertRaises(ValueError):
            call_command(
                "export_cashup_detail", salon_id=self.salon.pk,
                start_date=NEXT, end_date=DAY, stdout=io.StringIO())

    def test_values_match_underlying_detail_service(self):
        out = io.StringIO()
        call_command(
            "export_cashup_detail", salon_id=self.salon.pk,
            start_date=DAY, end_date=DAY, stdout=out)
        detail = cashup_detail(self.salon, DAY, DAY)
        self.assertIn("85.00", out.getvalue())
        self.assertEqual(detail.net, Decimal("85.00"))
