import datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client, ClientNote
from saloncore.models import Salon, Service, ServiceCategory, ServicePrice, StaffLevel
from team.models import RosterPattern, StaffMember


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
        for label in (
            "Home", "Daybook", "Clients", "Team", "Services",
            "POS", "Automations", "Insights", "Settings",
        ):
            self.assertContains(response, label)


class DayBookTests(WebuiTestBase):
    def test_staff_column_and_roster_shift_render(self):
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "Maribel Gonzalez")
        self.assertContains(response, "0% utilized")
        self.assertContains(response, "No appointments on the book")

    def test_no_roster_day_marks_member_not_rostered(self):
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-03"})
        self.assertContains(response, "Not rostered")

    def _appointment(self, start_hour=10, end_hour=11, status="confirmed"):
        return Appointment.objects.create(
            client=self.person,
            staff_member=self.member,
            service=self.service,
            start=timezone.make_aware(datetime.datetime(2026, 11, 2, start_hour, 0)),
            end=timezone.make_aware(datetime.datetime(2026, 11, 2, end_hour, 0)),
            status=status,
        )

    def test_feed_block_renders_into_the_right_column(self):
        self._appointment()
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "Jaime Orta")
        self.assertContains(response, "status-confirmed")
        self.assertContains(response, "cat-hair")
        self.assertNotContains(response, "No appointments on the book")

    def test_detail_rail_carries_the_full_record(self):
        appt = self._appointment()
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, 'id="detailRail"')
        self.assertContains(response, f'data-appt="{appt.pk}"')
        self.assertContains(response, "Service Stack")
        self.assertContains(response, "Jaime Orta")
        self.assertContains(response, "Maribel Gonzalez")
        self.assertContains(response, "Level 6")
        self.assertContains(response, "407-555-0100")
        self.assertContains(response, "Prefers Demi 4.5.")
        self.assertContains(response, 'id="rail-data"')

    def test_overview_and_intel_bar_compute_from_records(self):
        self._appointment(start_hour=10, end_hour=12)  # 120 of 480 rostered min
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "25% utilized")
        self.assertContains(response, "Projected Revenue")
        self.assertContains(response, "$85")
        self.assertContains(response, "Daybook Intelligence")
        self.assertContains(response, "Open Time Slots")

    def test_status_filter_narrows_the_book(self):
        self._appointment(status="confirmed")
        response = self.client.get(
            reverse("webui:daybook"), {"date": "2026-11-02", "status": "booked"}
        )
        # The rail still describes the day; the grid itself is empty.
        self.assertNotContains(response, "appt-block")

    def test_theme_is_dark(self):
        response = self.client.get(reverse("webui:daybook"))
        self.assertContains(response, 'data-theme="dark"')


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
        for name in (
            "webui:home", "webui:team", "webui:products", "webui:insights",
            "webui:pos", "webui:automations", "webui:settings",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
