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



class DayBookControlTests(WebuiTestBase):
    def test_week_strip_shows_seven_days_with_selection(self):
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-04"})
        self.assertContains(response, "week-strip")
        self.assertContains(response, "is-selected")
        for dom in ("2", "8"):  # Mon Nov 2 .. Sun Nov 8, 2026
            self.assertContains(response, f'<span class="week-dom">{dom}</span>', html=True)

    def test_date_jump_control_present(self):
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, 'type="date"')
        self.assertContains(response, 'value="2026-11-02"')

    def test_staff_chip_hides_column(self):
        url = reverse("webui:daybook")
        response = self.client.get(url, {"date": "2026-11-02", "off": str(self.member.pk)})
        self.assertNotContains(response, "db-staff-name\">Maribel Gonzalez")
        self.assertContains(response, "chip is-off")

    def _two_blocks(self):
        base = {
            "staff_id": self.member.pk,
            "client_name": "Jaime Orta",
            "service_name": "Women's Haircut",
            "note": "",
        }
        return [
            {**base, "start": datetime.time(10, 0), "end": datetime.time(11, 0), "status": "confirmed"},
            {**base, "start": datetime.time(12, 0), "end": datetime.time(13, 0), "status": "no_show"},
        ]

    def test_status_filter_limits_blocks(self):
        with mock.patch.object(views, "blocks_for_day", return_value=self._two_blocks()):
            response = self.client.get(
                reverse("webui:daybook"), {"date": "2026-11-02", "status": "confirmed"}
            )
        self.assertContains(response, "status-confirmed")
        self.assertNotContains(response, "status-no_show")

    def test_category_filter_limits_blocks(self):
        blocks = self._two_blocks()
        blocks[0]["category_id"] = self.category.pk
        blocks[1]["category_id"] = 999999
        with mock.patch.object(views, "blocks_for_day", return_value=blocks):
            response = self.client.get(
                reverse("webui:daybook"), {"date": "2026-11-02", "cat": str(self.category.pk)}
            )
        self.assertContains(response, "status-confirmed")
        self.assertNotContains(response, "status-no_show")

    def test_block_shows_category_colourway_and_status_label(self):
        block = {**self._two_blocks()[0], "category": "Hair", "category_id": self.category.pk}
        with mock.patch.object(views, "blocks_for_day", return_value=[block]):
            response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "--wash:#dce8d2")
        self.assertContains(response, "Confirmed")

    def test_break_contract_renders_paid_flag(self):
        brk = {
            "staff_id": self.member.pk,
            "start": datetime.time(13, 0),
            "end": datetime.time(13, 30),
            "paid": True,
            "label": "Lunch",
        }
        with mock.patch.object(views, "breaks_for_day", return_value=[brk]):
            response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "break-block is-paid")
        self.assertContains(response, "Paid")
        self.assertContains(response, "Lunch")


class PriceBookFilterTests(WebuiTestBase):
    def test_search_filters_services(self):
        response = self.client.get(reverse("webui:pricebook"), {"q": "nobody-service"})
        self.assertContains(response, "Nothing on the book matches")
        response = self.client.get(reverse("webui:pricebook"), {"q": "Haircut"})
        self.assertContains(response, "Women's Haircut", html=True)

    def test_category_chip_filters_groups(self):
        other = ServiceCategory.objects.create(name="Nails", salon=self.salon)
        Service.objects.create(name="Manicure", category=other, service_minutes=45)
        response = self.client.get(reverse("webui:pricebook"), {"cat": str(other.pk)})
        self.assertContains(response, "Manicure")
        self.assertNotContains(response, "Women's Haircut")


class ClientFilterTests(WebuiTestBase):
    def test_sms_filter(self):
        Client.objects.create(salon=self.salon, first_name="No", last_name="Optin")
        response = self.client.get(reverse("webui:clients"), {"opt": "sms"})
        self.assertContains(response, "Jaime Orta")
        self.assertNotContains(response, "No Optin")

    def test_notes_filter(self):
        Client.objects.create(salon=self.salon, first_name="Plain", last_name="Client")
        response = self.client.get(reverse("webui:clients"), {"opt": "notes"})
        self.assertContains(response, "Jaime Orta")
        self.assertNotContains(response, "Plain Client")
