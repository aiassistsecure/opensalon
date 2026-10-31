import datetime
from decimal import Decimal
from unittest import mock

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
        self.assertContains(response, "Level 6")
        self.assertContains(response, "0 visits")
        self.assertContains(response, "No appointments on the book")

    def test_unrostered_unbooked_member_has_no_column(self):
        # The working book: a stylist who is neither rostered nor
        # booked on the day gets no column at all.
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-03"})
        self.assertEqual(response.context["staff_columns"], [])
        self.assertNotContains(response, "Maribel Gonzalez")

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
        self.assertContains(response, "25%")
        self.assertContains(response, "Projected Revenue")
        self.assertContains(response, "$85")
        self.assertContains(response, "Daybook Intelligence")
        self.assertContains(response, "Top Book Today")
        self.assertContains(response, "Next Opening")

    def test_status_filter_narrows_the_book(self):
        self._appointment(status="confirmed")
        response = self.client.get(
            reverse("webui:daybook"), {"date": "2026-11-02", "status": "booked"}
        )
        # The rail still describes the day; the grid itself is empty.
        self.assertNotContains(response, "appt-block")

    def test_service_blocks_render_individually_phorest_style(self):
        # Founder direction (2026-10-31, with Phorest open beside
        # it): the grid unit is the service. A guest's stacked
        # services are separate blocks in the column; the VISIT
        # still exists for the agenda, the KPIs and the rail.
        self._appointment(start_hour=10, end_hour=11)
        self._appointment(start_hour=11, end_hour=12)
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        column = response.context["staff_columns"][0]
        self.assertEqual(len(column["blocks"]), 2)
        first, second = column["blocks"]
        self.assertEqual(first["price_label"], "$85")
        self.assertEqual(first["time_label"], "10 AM – 11 AM")
        self.assertEqual(second["time_label"], "11 AM – 12 PM")
        self.assertEqual(len(response.context["agenda"]), 1)
        self.assertEqual(response.context["overview"]["visits"], 1)
        self.assertEqual(response.context["overview"]["appointments"], 2)

    def test_base_price_fallback_when_level_has_no_row(self):
        base = StaffLevel.objects.create(name="Base", salon=self.salon)
        other_service = Service.objects.create(
            name="Gloss Treatment", category=self.category, service_minutes=30
        )
        ServicePrice.objects.create(
            service=other_service, staff_level=base, amount=Decimal("45.00")
        )
        Appointment.objects.create(
            client=self.person,
            staff_member=self.member,
            service=other_service,
            start=timezone.make_aware(datetime.datetime(2026, 11, 2, 10, 0)),
            end=timezone.make_aware(datetime.datetime(2026, 11, 2, 10, 30)),
            status="confirmed",
        )
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        tile = response.context["staff_columns"][0]["blocks"][0]
        self.assertEqual(tile["price_label"], "$45")
        self.assertEqual(response.context["overview"]["revenue"], Decimal("45.00"))
        self.assertEqual(response.context["overview"]["unpriced"], 0)

    def test_move_moves_the_grabbed_block_only(self):
        import json as jsonlib

        first = self._appointment(start_hour=10, end_hour=11)
        second = self._appointment(start_hour=11, end_hour=12)
        other_member = StaffMember.objects.create(
            display_name="Sonia Taylor", salon=self.salon, staff_level=self.level
        )
        response = self.client.post(
            reverse("webui:daybook_move"),
            data=jsonlib.dumps(
                {
                    "appointment_id": first.pk,
                    "staff_member_id": other_member.pk,
                    "start_minutes": 13 * 60 + 25,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["moved"], 1)
        first.refresh_from_db()
        self.assertEqual(first.staff_member_id, other_member.pk)
        self.assertEqual(first.start.hour, 13)
        self.assertEqual(first.start.minute, 25)
        # The block that was not grabbed does not travel with it:
        # blocks are individual services, Phorest-style.
        second.refresh_from_db()
        self.assertEqual(second.staff_member_id, self.member.pk)
        self.assertEqual(second.start.hour, 11)

    def test_move_snaps_to_five_minutes_and_validates(self):
        import json as jsonlib

        appt = self._appointment(start_hour=10, end_hour=11)
        response = self.client.post(
            reverse("webui:daybook_move"),
            data=jsonlib.dumps(
                {
                    "appointment_id": appt.pk,
                    "staff_member_id": self.member.pk,
                    "start_minutes": 12 * 60 + 32,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.json()["start_minutes"], 12 * 60 + 30)
        appt.refresh_from_db()
        self.assertEqual(appt.start.minute, 30)
        bad = self.client.post(
            reverse("webui:daybook_move"),
            data=jsonlib.dumps(
                {
                    "appointment_id": appt.pk,
                    "staff_member_id": 999999,
                    "start_minutes": 600,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(bad.status_code, 404)
        self.assertEqual(self.client.get(reverse("webui:daybook_move")).status_code, 405)

    def test_fragment_endpoint_renders_the_day_without_chrome(self):
        appt = self._appointment()
        response = self.client.get(
            reverse("webui:daybook_fragment"), {"date": "2026-11-02"}
        )
        self.assertContains(response, "book-layout")
        self.assertContains(response, f'data-appt="{appt.pk}"')
        self.assertContains(response, 'id="rail-data"')
        self.assertNotContains(response, 'class="side"')
        self.assertNotContains(response, "tabbar")

    def test_agenda_is_chronological_across_stylists(self):
        self._appointment(start_hour=14, end_hour=15)
        self._appointment(start_hour=9, end_hour=10)
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        agenda = response.context["agenda"]
        self.assertEqual(len(agenda), 2)
        self.assertTrue(agenda[0]["time_label"].startswith("9 AM"))
        self.assertTrue(agenda[1]["time_label"].startswith("2 PM"))
        self.assertContains(response, "acard")

    def test_snapshot_appointment_renders_under_recorded_name(self):
        # An appointment whose service is absent from the price book
        # carries only its verbatim snapshot name (service is NULL).
        # The block, the rail service stack and the client history
        # must all render it under that recorded name — never crash.
        Appointment.objects.create(
            client=self.person,
            staff_member=self.member,
            service=None,
            service_name="Color - With Ladies Haircut",
            start=timezone.make_aware(datetime.datetime(2026, 11, 2, 12, 30)),
            end=timezone.make_aware(datetime.datetime(2026, 11, 2, 14, 0)),
            status="completed",
        )
        Appointment.objects.create(
            client=self.person,
            staff_member=self.member,
            service=None,
            service_name="Color - With Ladies Haircut",
            start=timezone.make_aware(datetime.datetime(2026, 10, 26, 12, 30)),
            end=timezone.make_aware(datetime.datetime(2026, 10, 26, 14, 0)),
            status="completed",
        )
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        self.assertContains(response, "Color - With Ladies Haircut")
        self.assertContains(response, "Jaime Orta")

    def test_theme_is_dark(self):
        response = self.client.get(reverse("webui:daybook"))
        self.assertContains(response, 'data-theme="dark"')


class PrecisionTests(WebuiTestBase):
    def _appt(self, start, end, client=None):
        return Appointment.objects.create(
            client=client or self.person,
            staff_member=self.member,
            service=self.service,
            start=timezone.make_aware(start),
            end=timezone.make_aware(end),
            status="confirmed",
        )

    def test_now_line_follows_the_salon_timezone(self):
        # 2026-11-03 00:30 UTC is 2026-11-02 19:30 in New York: the
        # salon is still in Monday evening while the server clock
        # already calls it Tuesday. "Today" — and the now-line —
        # belong to the salon.
        self.salon.timezone = "America/New_York"
        self.salon.save(update_fields=["timezone"])
        fixed_now = datetime.datetime(
            2026, 11, 3, 0, 30, tzinfo=datetime.timezone.utc
        )
        with mock.patch.object(timezone, "now", return_value=fixed_now):
            response = self.client.get(
                reverse("webui:daybook"), {"date": "2026-11-02"}
            )
            self.assertEqual(response.context["today"], datetime.date(2026, 11, 2))
            self.assertContains(response, "nowline")
            self.assertContains(response, "7:30 PM")
            other = self.client.get(
                reverse("webui:daybook"), {"date": "2026-11-01"}
            )
            self.assertNotContains(other, "nowline")

    def test_crowded_column_widens_and_price_survives(self):
        first = self._appt(
            datetime.datetime(2026, 11, 2, 10, 0), datetime.datetime(2026, 11, 2, 10, 45)
        )
        # A second CLIENT double-booked into the same chair: two
        # distinct visits overlap, so the lane machinery — not the
        # visit merge — owns this case.
        other = Client.objects.create(
            salon=self.salon, first_name="Robin", last_name="Voss"
        )
        second = self._appt(
            datetime.datetime(2026, 11, 2, 10, 15),
            datetime.datetime(2026, 11, 2, 11, 0),
            client=other,
        )
        short = self._appt(
            datetime.datetime(2026, 11, 2, 12, 0), datetime.datetime(2026, 11, 2, 12, 20)
        )
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        column = response.context["staff_columns"][0]
        blocks = {b["appointment_id"]: b for b in column["blocks"]}
        # Two overlapping 45-minute blocks: crowded, but each keeps
        # its service and its price — neither degrades to mini.
        for appt in (first, second):
            self.assertEqual(blocks[appt.pk]["overlap"], 2)
            self.assertFalse(blocks[appt.pk]["mini"])
            self.assertEqual(blocks[appt.pk]["price_label"], "$85")
        # A 20-minute block is micro: too short for its rows.
        self.assertTrue(blocks[short.pk]["micro"])
        self.assertTrue(blocks[short.pk]["mini"])
        # The crowded column asks for double width in the grid tracks.
        self.assertEqual(column["width_factor"], 2)
        self.assertIn("var(--colunit) * 2", response.context["grid_tracks"])
        self.assertContains(response, "micro")


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


class PortableFormatTests(TestCase):
    """The label helpers must not use glibc-only strftime flags.

    Regression for the pilot install's first page load on Windows
    (2026-10-31): "%-I" / "%-d" raised ValueError there. These
    assertions pin the exact label shapes the UI renders.
    """

    def test_fmt_time_labels(self):
        from webui.views import _fmt_time

        self.assertEqual(_fmt_time(datetime.time(9, 0)), "9 AM")
        self.assertEqual(_fmt_time(datetime.time(9, 30)), "9:30 AM")
        self.assertEqual(_fmt_time(datetime.time(12, 0)), "12 PM")
        self.assertEqual(_fmt_time(datetime.time(0, 0)), "12 AM")
        self.assertEqual(_fmt_time(datetime.time(13, 5)), "1:05 PM")
        self.assertEqual(_fmt_time(datetime.time(23, 59)), "11:59 PM")

    def test_fmt_date_labels(self):
        from webui.views import _fmt_date_label

        day = datetime.date(2026, 10, 3)  # a Saturday
        self.assertEqual(_fmt_date_label(day), "Sat, Oct 3")
        self.assertEqual(_fmt_date_label(day, with_year=True),
                         "Sat, Oct 3, 2026")
