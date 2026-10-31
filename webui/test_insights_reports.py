"""Insights reports — the date-wise accounting + audit page.

Pins: one range drives every figure; the ledger is the checkout
lane's own daily summaries with refunds laid over (never a
second arithmetic); tenders come from the payments themselves;
voided sales vanish everywhere; the audit sections read the
append-only records; and each CSV download prints the same rows
its section shows.
"""
import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from checkout.models import Payment, Refund, Sale, SaleItem
from clients.models import Client
from messaging.models import ReminderSend
from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember


class InsightsReportsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Reports Salon", timezone="UTC", currency="USD"
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana Stylist"
        )
        self.guest = Client.objects.create(
            salon=self.salon,
            first_name="Robin", last_name="Guest",
            email="robin@example.com", phone="555-0110",
        )
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Cuts"
        )
        self.service = Service.objects.create(
            category=category, name="Signature Cut", service_minutes=60
        )
        self.now = timezone.now()
        self.today = self.now.date()
        self.yesterday = self.today - datetime.timedelta(days=1)

        def moment(day, hour=12):
            return timezone.make_aware(
                datetime.datetime.combine(day, datetime.time(hour, 0))
            )

        # The appointment attributes today's sale to Dana.
        self.appointment = Appointment.objects.create(
            client=self.guest,
            staff_member=self.staff,
            service=self.service,
            start=moment(self.today, 11),
            end=moment(self.today, 12),
            status="booked",
        )

        def sale(day, items, method, status=Sale.Status.COMPLETED):
            record = Sale.objects.create(
                salon=self.salon, client=self.guest, status=status,
                completed_at=moment(day, 13) if status != Sale.Status.OPEN else None,
            )
            total = Decimal("0")
            for kind, price in items:
                SaleItem.objects.create(
                    sale=record, kind=kind, unit_price=price, quantity=1,
                    service=self.service if kind == "service" else None,
                )
                total += price
            if status != Sale.Status.VOIDED:
                Payment.objects.create(
                    sale=record, method=method, amount=total,
                    status=Payment.Status.COMPLETED,
                )
            return record

        self.sale_today = sale(
            self.today,
            [("service", Decimal("100.00")), ("product", Decimal("36.00"))],
            Payment.Method.CASH,
        )
        self.sale_yesterday = sale(
            self.yesterday, [("service", Decimal("50.00"))],
            Payment.Method.EXTERNAL,
        )
        self.sale_voided = sale(
            self.today, [("service", Decimal("999.00"))],
            Payment.Method.CASH, status=Sale.Status.VOIDED,
        )
        Refund.objects.create(
            sale=self.sale_today, amount=Decimal("10.00"), tender="cash"
        )
        level = StaffLevel.objects.create(salon=self.salon, name="Level 1")
        price = ServicePrice.objects.create(
            service=self.service, staff_level=level, amount=Decimal("100.00")
        )
        self.change = PriceChange.objects.create(
            service_price=price, old_amount=Decimal("90.00"),
            new_amount=Decimal("100.00"), changed_by="Mark",
        )
        ReminderSend.objects.create(
            appointment=self.appointment, client=self.guest,
            channel="email", status="sent", detail="",
        )

    def get(self, **params):
        return self.client.get(reverse("webui:insights"), params)

    def test_default_range_page_carries_the_ledger(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        ledger = {row["day"]: row for row in response.context["ledger"]}
        today_row = ledger[self.today]
        self.assertEqual(today_row["service"], Decimal("100.00"))
        self.assertEqual(today_row["retail"], Decimal("36.00"))
        self.assertEqual(today_row["gross"], Decimal("136.00"))
        self.assertEqual(today_row["refunds"], Decimal("10.00"))
        self.assertEqual(today_row["net"], Decimal("126.00"))
        totals = response.context["totals"]
        self.assertEqual(totals["gross"], Decimal("186.00"))
        self.assertEqual(totals["net"], Decimal("176.00"))
        self.assertEqual(totals["count"], 2)

    def test_tenders_come_from_payments(self):
        response = self.get()
        rows = {row["method"]: row["amount"] for row in response.context["tender_rows"]}
        self.assertEqual(rows["cash"], Decimal("136.00"))
        self.assertEqual(rows["external"], Decimal("50.00"))
        self.assertIn("186", response.context["tender_total_label"])

    def test_custom_range_narrows_everything(self):
        response = self.get(
            preset="custom",
            start=self.yesterday.isoformat(),
            end=self.yesterday.isoformat(),
        )
        totals = response.context["totals"]
        self.assertEqual(totals["gross"], Decimal("50.00"))
        self.assertEqual(totals["count"], 1)
        self.assertEqual(response.context["refund_count"], 0)

    def test_voided_sale_is_nowhere(self):
        response = self.get()
        register_ids = [sale.pk for sale in response.context["register"]]
        self.assertIn(self.sale_today.pk, register_ids)
        self.assertNotIn(self.sale_voided.pk, register_ids)

    def test_audit_sections_read_the_records(self):
        response = self.get()
        changes = list(response.context["price_changes"])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].new_amount, Decimal("100.00"))
        self.assertEqual(response.context["send_counts"].get("email"), 1)
        self.assertContains(response, "Signature Cut")

    def test_staff_revenue_attributes_through_the_appointment(self):
        response = self.get()
        rows = {row["display_name"]: row["total"] for row in response.context["staff_rows"]}
        self.assertEqual(rows.get("Dana Stylist"), Decimal("136.00"))

    def test_bogus_preset_falls_back(self):
        response = self.get(preset="whenever")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["preset"], "30d")

    def test_csv_downloads_match_the_page(self):
        url = reverse("webui:insights_export", args=["ledger"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("date,sales,services,retail,gross,refunds,net", body)
        self.assertIn(f"{self.today.isoformat()},1,100.00,36.00,136.00,10.00,126.00", body)
        url = reverse("webui:insights_export", args=["prices"])
        body = self.client.get(url).content.decode()
        self.assertIn("Signature Cut", body)
        self.assertIn("90.00,100.00,Mark", body)
        url = reverse("webui:insights_export", args=["register"])
        body = self.client.get(url).content.decode()
        self.assertIn("136.00", body)
        self.assertNotIn("999.00", body)

    def test_unknown_export_kind_redirects(self):
        url = reverse("webui:insights_export", args=["everything"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
