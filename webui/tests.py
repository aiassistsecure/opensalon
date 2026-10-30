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
        for label in ("Day Book", "Clients", "Price Book", "Team", "Products", "Reports"):
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
        self.assertContains(response, "Women&#x27;s Haircut")
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
        # Hair maps to the mock's forest colourway, worn as the
        # block's saturated gradient.
        self.assertContains(response, "--block-bg:linear-gradient(150deg,#39684a,#254a33)")
        self.assertContains(response, "Confirmed")
        self.assertContains(response, "✓")

    def test_block_shows_price_label_when_priced(self):
        block = {**self._two_blocks()[0], "price": Decimal("85.00")}
        with mock.patch.object(views, "blocks_for_day", return_value=[block]):
            response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "appt-price")
        self.assertContains(response, "$85")

    def test_staff_head_shows_signature_band_and_booked_label(self):
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "--band:linear-gradient(150deg,#26503c,#173327)")
        # Rostered 9–5 with nothing booked yet reads as openings —
        # the booked figure is computed, never invented.
        self.assertContains(response, "Openings")

    def test_booked_label_counts_real_blocks_against_roster(self):
        # Four booked hours against an eight-hour roster = 50%.
        block = {
            "staff_id": self.member.pk, "client_name": "Jaime Orta",
            "service_name": "Women's Haircut", "start": datetime.time(9, 0),
            "end": datetime.time(13, 0), "status": "confirmed", "note": "",
        }
        with mock.patch.object(views, "blocks_for_day", return_value=[block]):
            response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "Booked 50%")

    def test_action_bar_renders_with_selection_prompt(self):
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, 'id="actionbar"')
        self.assertContains(response, "Select an appointment to act on it")
        self.assertContains(response, "Pay — Close Out")

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
        self.assertContains(response, "Women&#x27;s Haircut")

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



from types import SimpleNamespace

from webui import interactions


def _visit_dict(**overrides):
    visit = {
        "id": 7,
        "client_id": 3,
        "client_name": "Jaime Orta",
        "staff_id": 2,
        "staff_name": "Maribel Gonzalez",
        "date": datetime.date(2026, 11, 2),
        "start": datetime.time(10, 0),
        "end": datetime.time(11, 30),
        "status": "confirmed",
        "lines": [
            {"appointment_id": 7, "service_name": "Women's Haircut",
             "duration_label": "1h", "price": Decimal("85.00"), "price_is_from": False},
            {"appointment_id": 8, "service_name": "Toner (add-on)",
             "duration_label": "30m", "price": Decimal("40.00"), "price_is_from": False},
        ],
        "total": Decimal("125.00"),
        "appointment_notes": [SimpleNamespace(body="Running 10 late", author_name="Desk", created_at=None)],
        "record_notes": [SimpleNamespace(body="Prefers Demi 4.5.", author_name="", created_at=None)],
    }
    visit.update(overrides)
    return visit


class BreakdownTests(WebuiTestBase):
    def test_pending_state_is_honest_without_bookings(self):
        response = self.client.get(reverse("webui:breakdown", args=[7]))
        self.assertContains(response, "opens with the bookings lane")
        self.assertNotContains(response, "Total")

    def test_breakdown_renders_lines_total_and_both_note_kinds(self):
        with mock.patch.object(
            interactions, "breakdown_for_appointment", return_value=_visit_dict()
        ):
            response = self.client.get(reverse("webui:breakdown", args=[7]))
        self.assertContains(response, "Jaime Orta")
        self.assertContains(response, "Women&#x27;s Haircut")
        self.assertContains(response, "Toner (add-on)")
        self.assertContains(response, "$125.00")
        self.assertContains(response, "Appointment notes — this visit only")
        self.assertContains(response, "Client record notes — every visit")
        self.assertContains(response, "Running 10 late")
        self.assertContains(response, "Prefers Demi 4.5.")
        self.assertContains(response, "Pay — close out")
        self.assertContains(response, "Copy")

    def test_add_service_post_reports_nothing_added_when_contracted(self):
        with mock.patch.object(
            interactions, "breakdown_for_appointment", return_value=_visit_dict()
        ):
            response = self.client.post(
                reverse("webui:add_service", args=[7]), {"service": self.service.pk}
            )
        self.assertContains(response, "nothing was added")

    def test_close_out_shows_total_and_never_a_payment_form(self):
        with mock.patch.object(
            interactions, "breakdown_for_appointment", return_value=_visit_dict()
        ):
            response = self.client.get(reverse("webui:close_out", args=[7]))
            self.assertContains(response, "$125.00")
            self.assertNotContains(response, 'name="card')
            response = self.client.post(reverse("webui:close_out", args=[7]))
        self.assertContains(response, "no payment was taken")


class ActionBarActionTests(WebuiTestBase):
    def test_check_in_post_is_honest_when_not_wired(self):
        # Without the bookings lane there is no status to write: the
        # action lands on the breakdown's plain pending state and
        # never claims the client was checked in.
        response = self.client.post(
            reverse("webui:appointment_action", args=[7, "check-in"])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("webui:breakdown", args=[7]))

    def test_unknown_action_falls_back_to_breakdown(self):
        response = self.client.post(
            reverse("webui:appointment_action", args=[7, "teleport"])
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("webui:breakdown", args=[7]))


class BookingFormTests(WebuiTestBase):
    def test_form_prefills_stylist_day_and_time_from_the_click(self):
        response = self.client.get(
            reverse("webui:appointment_new"),
            {"staff": self.member.pk, "date": "2026-11-02", "start": "10:30"},
        )
        self.assertContains(response, 'value="10:30:00"')
        self.assertContains(response, "Women&#x27;s Haircut · 60 min · $85.00")

    def test_booking_post_is_honest_when_not_wired(self):
        response = self.client.post(
            reverse("webui:appointment_new"),
            {
                "client_id": self.person.pk,
                "client_name": "Jaime Orta",
                "service": self.service.pk,
                "staff": self.member.pk,
                "date": "2026-11-02",
                "start": "10:00",
                "note": "First visit",
            },
        )
        self.assertContains(response, "nothing was booked")


class CopyTests(WebuiTestBase):
    def test_copy_page_prefills_target_from_click_model(self):
        response = self.client.get(
            reverse("webui:appointment_copy"),
            {"source": 7, "staff": self.member.pk, "date": "2026-11-03", "start": "14:00"},
        )
        self.assertContains(response, 'name="source" value="7"')
        self.assertContains(response, 'value="14:00:00"')

    def test_copy_post_is_honest_when_not_wired(self):
        response = self.client.post(
            reverse("webui:appointment_copy"),
            {"source": 7, "staff": self.member.pk, "date": "2026-11-03", "start": "14:00"},
        )
        self.assertContains(response, "no copy was placed")


class BreakFormTests(WebuiTestBase):
    def test_break_form_has_paid_flag_and_prefill(self):
        response = self.client.get(
            reverse("webui:break_new"),
            {"staff": self.member.pk, "date": "2026-11-02", "start": "13:00"},
        )
        self.assertContains(response, "Paid break")
        self.assertContains(response, 'name="paid"')
        self.assertContains(response, 'value="13:00:00"')

    def test_break_post_is_honest_when_not_wired(self):
        response = self.client.post(
            reverse("webui:break_new"),
            {
                "staff": self.member.pk, "date": "2026-11-02", "start": "13:00",
                "minutes": 30, "label": "Lunch", "paid": "on",
            },
        )
        self.assertContains(response, "no break was saved")


class ClickModelMarkupTests(WebuiTestBase):
    def test_day_book_carries_copy_toggle_and_column_data(self):
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, 'id="copy-toggle"')
        self.assertContains(response, f'data-staff-id="{self.member.pk}"')
        self.assertContains(response, "＋ Break")

    def test_block_with_appointment_id_links_to_breakdown(self):
        block = {
            "staff_id": self.member.pk, "client_name": "Jaime Orta",
            "service_name": "Women's Haircut", "start": datetime.time(10, 0),
            "end": datetime.time(11, 0), "status": "arrived", "note": "",
            "appointment_id": 7,
        }
        with mock.patch.object(views, "blocks_for_day", return_value=[block]):
            response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, 'href="/appointment/7/"')
        self.assertContains(response, 'data-appt-id="7"')
        self.assertContains(response, "status-arrived")

    def test_block_mapping_from_appointment_row(self):
        note = SimpleNamespace(body="Allergic to ammonia")
        appt = SimpleNamespace(
            staff_member_id=5, client="Jaime Orta",
            service=SimpleNamespace(
                name="Full Highlight", category=SimpleNamespace(name="Color"),
                category_id=9,
            ),
            start=datetime.datetime(2026, 11, 2, 10, 0, tzinfo=datetime.timezone.utc),
            end=datetime.datetime(2026, 11, 2, 12, 0, tzinfo=datetime.timezone.utc),
            status="booked", pk=7,
            notes=SimpleNamespace(all=lambda: [note]),
        )
        block = views._block_from_appointment(appt)
        self.assertEqual(block["appointment_id"], 7)
        self.assertEqual(block["category"], "Color")
        self.assertEqual(block["note"], "Allergic to ammonia")
        self.assertEqual(block["status"], "booked")

    def test_blocks_contract_empty_until_bookings_lands(self):
        self.assertEqual(views.blocks_for_day(self.salon, datetime.date(2026, 11, 2)), [])
        self.assertEqual(views.breaks_for_day(self.salon, datetime.date(2026, 11, 2)), [])


class SidebarShellTests(TestCase):
    """The collapsible glass sidebar: cookie-rendered width, the
    toggle endpoint, and labels that survive the rail."""

    def setUp(self):
        Salon.objects.create(name="Mint On The Avenue")

    def test_sidebar_expanded_without_cookie(self):
        response = self.client.get(reverse("webui:daybook"))
        self.assertContains(response, "<body>")
        self.assertNotContains(response, 'class="is-rail"')
        # The toggle offers the collapse, expanded state announced.
        self.assertContains(response, 'aria-expanded="true"')
        self.assertContains(response, 'aria-label="Collapse sidebar"')

    def test_sidebar_rail_from_cookie(self):
        self.client.cookies["os_sidebar"] = "rail"
        response = self.client.get(reverse("webui:pricebook"))
        self.assertContains(response, '<body class="is-rail">')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, 'aria-label="Expand sidebar"')
        # Nav keeps its names for tooltips / assistive tech.
        self.assertContains(response, 'aria-label="Day Book"')
        self.assertContains(response, 'aria-label="Price Book"')

    def test_toggle_sets_cookie_and_returns(self):
        response = self.client.post(
            reverse("webui:sidebar_toggle"),
            {"state": "rail", "next": "/price-book/"},
        )
        self.assertRedirects(
            response, "/price-book/", fetch_redirect_response=False
        )
        self.assertEqual(response.cookies["os_sidebar"].value, "rail")

    def test_toggle_rejects_external_next(self):
        response = self.client.post(
            reverse("webui:sidebar_toggle"),
            {"state": "full", "next": "https://example.com/"},
        )
        self.assertRedirects(
            response, reverse("webui:daybook"), fetch_redirect_response=False
        )
        self.assertEqual(response.cookies["os_sidebar"].value, "full")

    def test_toggle_is_post_only(self):
        response = self.client.get(reverse("webui:sidebar_toggle"))
        self.assertEqual(response.status_code, 405)
