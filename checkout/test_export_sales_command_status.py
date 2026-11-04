"""export_sales command --status: thin wrapper over the service."""
import datetime
import io
from decimal import Decimal

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from checkout.models import Sale
from checkout.sale_export import export_sales_csv
from saloncore.models import Salon

DAY = datetime.date(2026, 10, 3)
NEXT = DAY + datetime.timedelta(days=1)


def _stamp(day, hour=12):
    return timezone.make_aware(
        datetime.datetime.combine(day, datetime.time(hour, 0)),
        datetime.timezone.utc)


class ExportSalesCommandStatusTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Sale Salon", timezone="UTC")

    def _sale(self, status, day=DAY):
        sale = Sale.objects.create(
            salon=self.salon, status=status,
            discount_amount=Decimal("10.00"))
        Sale.objects.filter(pk=sale.pk).update(created_at=_stamp(day))
        return sale

    def test_status_flag_matches_service(self):
        self._sale(Sale.Status.COMPLETED)
        voided = self._sale(Sale.Status.VOIDED)
        out = io.StringIO()
        call_command(
            "export_sales", "--salon-id", str(self.salon.pk),
            "--status", "voided", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sales_csv(self.salon, status=Sale.Status.VOIDED))
        self.assertIn(str(voided.pk), out.getvalue())

    def test_status_kwarg_and_default(self):
        self._sale(Sale.Status.COMPLETED)
        self._sale(Sale.Status.OPEN)
        out = io.StringIO()
        call_command(
            "export_sales", salon_id=self.salon.pk,
            status="open", stdout=out)
        self.assertEqual(
            out.getvalue(), export_sales_csv(self.salon, status="open"))
        out = io.StringIO()
        call_command("export_sales", salon_id=self.salon.pk, stdout=out)
        self.assertEqual(out.getvalue(), export_sales_csv(self.salon))

    def test_status_composes_with_dates(self):
        self._sale(Sale.Status.COMPLETED, DAY)
        kept = self._sale(Sale.Status.COMPLETED, NEXT)
        self._sale(Sale.Status.VOIDED, NEXT)
        out = io.StringIO()
        call_command(
            "export_sales", "--salon-id", str(self.salon.pk),
            "--start-date", NEXT.isoformat(),
            "--end-date", NEXT.isoformat(),
            "--status", "completed", stdout=out)
        self.assertEqual(
            out.getvalue(),
            export_sales_csv(self.salon, NEXT, NEXT, status="completed"))
        self.assertIn(str(kept.pk), out.getvalue())
        self.assertEqual(len(out.getvalue().strip().splitlines()), 2)

    def test_unknown_status_is_header_only(self):
        self._sale(Sale.Status.COMPLETED)
        out = io.StringIO()
        call_command(
            "export_sales", salon_id=self.salon.pk,
            status="nope", stdout=out)
        self.assertEqual(
            out.getvalue(), export_sales_csv(self.salon, status="nope"))
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)
