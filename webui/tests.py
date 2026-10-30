import datetime
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from clients.models import Client, ClientNote
from saloncore.models import Salon, Service, ServiceCategory, ServicePrice, StaffLevel
from team.models import RosterPattern, StaffMember
from webui import views


class WebuiTestBase(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.level = StaffLevel.objects.create(name="Level 6", salon=self.salon)
        self.category = ServiceCategory.objects.create(name="Hair", salon=self.salon)
        self.service = Service.objects.create(
            name="Women's Haircut", category=self.category, service_minutes=60
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level, amount=Decimal("85.00")
        )
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon, staff_level=self.level
        )
        # 2026-11-02 is a Monday.
        RosterPattern.objects.create(
            staff_member=self.member,
            weekday=RosterPattern.Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        self.person = Client.objects.create(
            salon=self.salon,
            first_name="Jaime",
            last_name="Orta",
            phone="407-555-0100",
            sms_opt_in=True,
        )
        ClientNote.objects.create(client=self.person, body="Prefers Demi 4.5.")


class ShellTests(WebuiTestBase):
    def test_header_shows_salon_name_and_nav(self):
        response = self.client.get(reverse("webui:daybook"))
        self.assertContains(response, "Mint On The Avenue")
        for label in ("Day Book", "Clients", "Price Book", "Team", "Products", "Insights"):
            self.assertContains(response, label)


class DayBookTests(WebuiTestBase):
    def test_staff_column_and_roster_shift_render(self):
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "Maribel Gonzalez")
        self.assertContains(response, "9 AM – 5 PM")
        self.assertContains(response, "No appointments on the book")

    def test_no_roster_day_marks_member_not_rostered(self):
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-03"})
        self.assertContains(response, "Not rostered")

    def test_block_contract_renders_into_the_right_column(self):
        block = {
            "staff_id": self.member.pk,
            "client_name": "Jaime Orta",
            "service_name": "Women's Haircut",
            "start": datetime.time(10, 0),
            "end": datetime.time(11, 0),
            "status": "confirmed",
            "note": "",
        }
        with mock.patch.object(views, "blocks_for_day", return_value=[block]):
            response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "Jaime Orta")
        self.assertContains(response, "status-confirmed")
        self.assertNotContains(response, "No appointments on the book")


class PriceBookTests(WebuiTestBase):
    def test_real_prices_render_grouped_by_category(self):
        response = self.client.get(reverse("webui:pricebook"))
        self.assertContains(response, "Hair")
        self.assertContains(response, "Women's Haircut", html=True)
        self.assertContains(response, "$85.00")
        self.assertContains(response, "1h")


class ClientPageTests(WebuiTestBase):
    def test_opt_in_badges_and_note_indicator(self):
        response = self.client.get(reverse("webui:clients"))
        self.assertContains(response, "Jaime Orta")
        self.assertContains(response, "SMS ✓")
        self.assertContains(response, "Email off")
        self.assertContains(response, "Notes · 1")

    def test_search_filters(self):
        response = self.client.get(reverse("webui:clients"), {"q": "nobody"})
        self.assertContains(response, "No clients match")
        response = self.client.get(reverse("webui:clients"), {"q": "Orta"})
        self.assertContains(response, "Jaime Orta")


class PlaceholderTests(WebuiTestBase):
    def test_lane_pages_render(self):
        for name in ("webui:team", "webui:products", "webui:insights"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
