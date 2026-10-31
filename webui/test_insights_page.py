"""Insights page: the spec figures, read from the insights lane."""
import datetime
from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from checkout.models import Sale, SaleItem
from clients.models import Client as SalonClient
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember


class InsightsPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(name="Mint", timezone="America/New_York")
        self.url = reverse("webui:insights")
        level = StaffLevel.objects.create(salon=self.salon, name="Level 6")
        self.member = StaffMember.objects.create(
            salon=self.salon, display_name="Dawn Davalos", staff_level=level
        )
        guest = SalonClient.objects.create(salon=self.salon, first_name="Krystal")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Women's Haircut", service_minutes=60
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=level, amount=Decimal("65.00")
        )
        sale = Sale.objects.create(
            salon=self.salon, client=guest, status=Sale.Status.COMPLETED,
            completed_at=timezone.now(),
        )
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.SERVICE, description="Cut",
            quantity=1, unit_price=Decimal("65.00"), service=self.service,
        )
        SaleItem.objects.create(
            sale=sale, kind=SaleItem.Kind.PRODUCT, description="Conditioner",
            quantity=1, unit_price=Decimal("26.00"),
        )
        start = timezone.now() + datetime.timedelta(days=1)
        Appointment.objects.create(
            client=guest, staff_member=self.member,
            service=self.service, start=start,
            end=start + datetime.timedelta(minutes=60),
            status=Appointment.Status.BOOKED,
        )

    def test_split_counts_services_and_retail(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("$65", html)
        self.assertIn("$26", html)
        self.assertIn("$91", html)

    def test_future_book_is_priced_from_the_price_book(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("The future book", html)
        # the one future appointment at the $65 price
        self.assertIn("$65", html)

    def test_busiest_days_render(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("Busiest days", html)
