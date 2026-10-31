import datetime
import json
from decimal import Decimal
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from webui.views import _amount_for, _price_lookup
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
        self._appointment()
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

        first = self._appointment()
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

        appt = self._appointment()
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


class WritePathTests(WebuiTestBase):
    def _make_appt(self, start_hour=10, end_hour=11):
        return Appointment.objects.create(
            client=self.person,
            staff_member=self.member,
            service=self.service,
            start=timezone.make_aware(
                datetime.datetime(2026, 11, 2, start_hour, 0)
            ),
            end=timezone.make_aware(
                datetime.datetime(2026, 11, 2, end_hour, 0)
            ),
            status="confirmed",
        )

    def _post(self, url_name, payload):
        import json as jsonlib

        return self.client.post(
            reverse(url_name),
            data=jsonlib.dumps(payload),
            content_type="application/json",
        )

    def test_status_flow_check_in_to_complete(self):
        appt = self._make_appt()
        self.assertEqual(appt.status, "confirmed")
        response = self._post(
            "webui:daybook_status", {"appointment_id": appt.pk, "status": "arrived"}
        )
        self.assertEqual(response.status_code, 200)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "arrived")
        # Skipping a step is rejected: arrived cannot jump to completed.
        response = self._post(
            "webui:daybook_status", {"appointment_id": appt.pk, "status": "completed"}
        )
        self.assertEqual(response.status_code, 400)
        self._post(
            "webui:daybook_status", {"appointment_id": appt.pk, "status": "in_service"}
        )
        self._post(
            "webui:daybook_status", {"appointment_id": appt.pk, "status": "completed"}
        )
        appt.refresh_from_db()
        self.assertEqual(appt.status, "completed")
        # Terminal: nothing leaves completed.
        response = self._post(
            "webui:daybook_status", {"appointment_id": appt.pk, "status": "arrived"}
        )
        self.assertEqual(response.status_code, 400)
        response = self._post(
            "webui:daybook_status", {"appointment_id": 999999, "status": "arrived"}
        )
        self.assertEqual(response.status_code, 404)

    def test_rail_payload_offers_check_in_as_a_toggle(self):
        self._make_appt()
        response = self.client.get(reverse("webui:daybook"), {"date": "2026-11-02"})
        toggles = [
            t
            for payload in response.context["rail_data"].values()
            for t in payload["toggles"]
        ]
        checkin = next(t for t in toggles if t["key"] == "checkin")
        self.assertFalse(checkin["on"])
        self.assertTrue(checkin["enabled"])
        self.assertEqual(checkin["target"], "arrived")
        noshow = next(t for t in toggles if t["key"] == "noshow")
        self.assertFalse(noshow["on"])
        self.assertEqual(noshow["target"], "no_show")
        # The button row no longer duplicates the toggles.
        labels = [
            a["label"]
            for payload in response.context["rail_data"].values()
            for a in payload["actions"]
        ]
        self.assertNotIn("Check In", labels)
        self.assertNotIn("No-show", labels)

    def test_check_in_toggle_reverses(self):
        appt = self._make_appt()
        for target, expected in (
            ("arrived", "arrived"),
            ("booked", "booked"),
            ("arrived", "arrived"),
        ):
            response = self._post(
                "webui:daybook_status",
                {"appointment_id": appt.pk, "status": target},
            )
            self.assertEqual(response.status_code, 200)
            appt.refresh_from_db()
            self.assertEqual(appt.status, expected)

    def test_no_show_toggle_reverses_but_cannot_start_service(self):
        appt = self._make_appt()
        response = self._post(
            "webui:daybook_status",
            {"appointment_id": appt.pk, "status": "no_show"},
        )
        self.assertEqual(response.status_code, 200)
        response = self._post(
            "webui:daybook_status",
            {"appointment_id": appt.pk, "status": "in_service"},
        )
        self.assertEqual(response.status_code, 400)
        response = self._post(
            "webui:daybook_status",
            {"appointment_id": appt.pk, "status": "booked"},
        )
        self.assertEqual(response.status_code, 200)
        appt.refresh_from_db()
        self.assertEqual(appt.status, "booked")

    def test_book_for_existing_client_uses_service_minutes(self):
        response = self._post(
            "webui:daybook_book",
            {
                "client_id": self.person.pk,
                "staff_member_id": self.member.pk,
                "service_id": self.service.pk,
                "date": "2026-11-02",
                "time": "13:30",
            },
        )
        self.assertEqual(response.status_code, 200)
        appt = Appointment.objects.get(pk=response.json()["appointment_id"])
        self.assertEqual(appt.status, "booked")
        self.assertEqual(appt.service_name, "Women's Haircut")
        self.assertEqual((appt.end - appt.start).total_seconds(), 60 * 60)
        self.assertEqual(appt.start.hour, 13)

    def test_book_creates_a_new_client_when_asked(self):
        response = self._post(
            "webui:daybook_book",
            {
                "new_client": {
                    "first_name": "Robin",
                    "last_name": "Voss",
                    "phone": "407-555-0199",
                },
                "staff_member_id": self.member.pk,
                "service_id": self.service.pk,
                "date": "2026-11-02",
                "time": "09:00",
            },
        )
        self.assertEqual(response.status_code, 200)
        appt = Appointment.objects.get(pk=response.json()["appointment_id"])
        self.assertEqual(appt.client.first_name, "Robin")
        self.assertEqual(appt.client.phone, "407-555-0199")

    def test_book_without_a_client_is_rejected(self):
        response = self._post(
            "webui:daybook_book",
            {
                "staff_member_id": self.member.pk,
                "service_id": self.service.pk,
                "date": "2026-11-02",
                "time": "09:00",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_client_search_and_options(self):
        response = self.client.get(reverse("webui:daybook_client_search"), {"q": "Orta"})
        self.assertEqual(
            [c["name"] for c in response.json()["clients"]], ["Jaime Orta"]
        )
        response = self.client.get(
            reverse("webui:daybook_client_search"), {"q": "5550100"}
        )
        self.assertEqual(len(response.json()["clients"]), 1)
        response = self.client.get(reverse("webui:daybook_book_options"))
        data = response.json()
        self.assertEqual([m["name"] for m in data["members"]], ["Maribel Gonzalez"])
        self.assertEqual(data["services"][0]["minutes"], 60)


class ApplyBatchTests(WritePathTests):
    """The drain endpoint: batches from the embedded store."""

    def _apply(self, ops):
        return self.client.post(
            reverse("webui:daybook_apply"),
            data=json.dumps({"ops": ops}),
            content_type="application/json",
        )

    def test_batch_applies_moves_and_statuses(self):
        appt = self._make_appt()
        response = self._apply(
            [
                {"kind": "status", "id": appt.pk, "status": "arrived"},
                {
                    "kind": "move",
                    "id": appt.pk,
                    "staff_member_id": self.member.pk,
                    "start_minutes": 663,
                },
            ]
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual([r["ok"] for r in data["results"]], [True, True])
        appt.refresh_from_db()
        self.assertEqual(appt.status, "arrived")
        # 663 snaps to 665 (11:05) — the batch obeys the same law,
        # and the move preserves the appointment's duration.
        self.assertEqual(data["results"][1]["start_minutes"], 665)
        self.assertEqual((appt.end - appt.start).total_seconds(), 60 * 60)

    def test_one_bad_op_never_poisons_the_batch(self):
        appt = self._make_appt()
        response = self._apply(
            [
                {"kind": "status", "id": appt.pk, "status": "completed"},
                {"kind": "status", "id": appt.pk, "status": "arrived"},
                {"kind": "status", "id": 999999, "status": "arrived"},
                {"kind": "teleport", "id": appt.pk},
            ]
        )
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(
            [r["ok"] for r in data["results"]], [False, True, False, False]
        )
        self.assertIn("cannot move", data["results"][0]["error"])
        appt.refresh_from_db()
        self.assertEqual(appt.status, "arrived")

    def test_batch_cap_and_shape(self):
        response = self._apply([{"kind": "status", "id": 1, "status": "arrived"}] * 101)
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            reverse("webui:daybook_apply"),
            data=json.dumps({"nope": []}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class CardEditTests(WritePathTests):
    """The client card's editors: prices and notes, one law for
    the single-op endpoints and the batch drain alike."""

    def test_price_single_op_sets_and_clears_override(self):
        appt = self._make_appt()
        response = self._post(
            "webui:daybook_price", {"appointment_id": appt.pk, "price": "72.50"}
        )
        self.assertEqual(response.status_code, 200)
        appt.refresh_from_db()
        self.assertEqual(appt.price_override, Decimal("72.50"))
        # The card's price wins over the book everywhere it is read.
        prices, base_id = _price_lookup(self.salon)
        self.assertEqual(_amount_for(appt, prices, base_id), Decimal("72.50"))
        response = self._post(
            "webui:daybook_price", {"appointment_id": appt.pk, "price": ""}
        )
        self.assertEqual(response.status_code, 200)
        appt.refresh_from_db()
        self.assertIsNone(appt.price_override)

    def test_price_rejects_bad_money(self):
        appt = self._make_appt()
        for bad in ("abc", "-5", "NaN", "100000"):
            response = self._post(
                "webui:daybook_price", {"appointment_id": appt.pk, "price": bad}
            )
            self.assertEqual(response.status_code, 400, bad)
        appt.refresh_from_db()
        self.assertIsNone(appt.price_override)

    def test_price_via_batch_drain(self):
        appt = self._make_appt()
        response = self.client.post(
            reverse("webui:daybook_apply"),
            data=json.dumps(
                {"ops": [{"kind": "price", "id": appt.pk, "price": "88"}]}
            ),
            content_type="application/json",
        )
        self.assertTrue(response.json()["ok"])
        appt.refresh_from_db()
        self.assertEqual(appt.price_override, Decimal("88.00"))

    def test_notes_two_kinds_never_blur(self):
        appt = self._make_appt()
        other = self._make_appt(start_hour=12, end_hour=13)
        response = self._post(
            "webui:daybook_note",
            {"appointment_id": appt.pk, "scope": "appt", "body": "Allergic to X"},
        )
        self.assertEqual(response.status_code, 200)
        response = self._post(
            "webui:daybook_note",
            {"appointment_id": appt.pk, "scope": "client", "body": "Prefers quiet"},
        )
        self.assertEqual(response.status_code, 200)
        note = AppointmentNote.objects.get(appointment=appt)
        self.assertEqual(note.body, "Allergic to X")
        self.assertEqual(
            ClientNote.objects.get(client=self.person, body="Prefers quiet").body,
            "Prefers quiet",
        )
        # Edit reaches only the note that belongs to its target.
        response = self._post(
            "webui:daybook_note",
            {
                "appointment_id": other.pk,
                "scope": "appt",
                "note_id": note.pk,
                "body": "Hijacked",
            },
        )
        self.assertEqual(response.status_code, 400)
        note.refresh_from_db()
        self.assertEqual(note.body, "Allergic to X")
        response = self._post(
            "webui:daybook_note",
            {
                "appointment_id": appt.pk,
                "scope": "appt",
                "note_id": note.pk,
                "body": "Allergic to Y",
            },
        )
        self.assertEqual(response.status_code, 200)
        note.refresh_from_db()
        self.assertEqual(note.body, "Allergic to Y")

    def test_writes_stamp_themselves(self):
        """The pack version is (count, max updated_at): a desk
        write that leaves updated_at standing still tells every
        polling client 'nothing changed' and the mirror never
        converges. Each write core must move its own stamp."""
        appt = self._make_appt()
        before = appt.updated_at
        response = self._post(
            "webui:daybook_status", {"appointment_id": appt.pk, "status": "arrived"}
        )
        self.assertEqual(response.status_code, 200)
        appt.refresh_from_db()
        self.assertGreater(appt.updated_at, before)
        before = appt.updated_at
        response = self._post(
            "webui:daybook_price", {"appointment_id": appt.pk, "price": "70"}
        )
        self.assertEqual(response.status_code, 200)
        appt.refresh_from_db()
        self.assertGreater(appt.updated_at, before)

    def test_pack_version_moves_after_a_drained_write(self):
        appt = self._make_appt()
        pack_url = reverse("webui:daybook_pack") + "?date=2026-11-02"
        v1 = self.client.get(pack_url).json()["version"]
        response = self.client.post(
            reverse("webui:daybook_apply"),
            data=json.dumps(
                {"ops": [{"kind": "status", "id": appt.pk, "status": "arrived"}]}
            ),
            content_type="application/json",
        )
        self.assertTrue(response.json()["ok"])
        data = self.client.get(pack_url).json()
        self.assertNotEqual(data["version"], v1)
        entry = [
            e for e in data["days"]["2026-11-02"] if e["id"] == appt.pk
        ][0]
        self.assertEqual(entry["status"], "arrived")

    def test_appointment_outside_the_window_still_has_a_card(self):
        """The visible window is 8-20, but the feed runs on
        midnight bounds: an early appointment always rendered a
        block while the window-bounded rail lookup missed it —
        and the payload build crashed on the miss. One fetch on
        midnight bounds serves grid and rail alike now."""
        early = Appointment.objects.create(
            client=self.person,
            staff_member=self.member,
            service=self.service,
            start=timezone.make_aware(datetime.datetime(2026, 11, 2, 7, 0)),
            end=timezone.make_aware(datetime.datetime(2026, 11, 2, 7, 45)),
            status="booked",
        )
        url = reverse("webui:daybook") + "?date=2026-11-02"
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Jaime Orta")
        pack = self.client.get(
            reverse("webui:daybook_pack") + "?date=2026-11-02"
        ).json()
        self.assertIn(
            early.pk, [e["id"] for e in pack["days"]["2026-11-02"]]
        )

    def test_pack_marks_first_visit_clients_new(self):
        """One rule for the ribbon count and the block glow:
        a client is new on the day of their first-ever visit."""
        appt = self._make_appt()
        url = reverse("webui:daybook_pack") + "?date=2026-11-02"

        def entry():
            data = self.client.get(url).json()
            return [e for e in data["days"]["2026-11-02"] if e["id"] == appt.pk][0]

        self.assertTrue(entry()["is_new"])
        Appointment.objects.create(
            client=self.person,
            staff_member=self.member,
            service=self.service,
            start=timezone.make_aware(datetime.datetime(2026, 10, 20, 10, 0)),
            end=timezone.make_aware(datetime.datetime(2026, 10, 20, 11, 0)),
            status="completed",
        )
        self.assertFalse(entry()["is_new"])

    def test_note_add_replay_does_not_duplicate(self):
        """The durable queue may re-send an add whose ack died
        with the tab: an identical note on the same target is
        that add, applied once — never a twin."""
        appt = self._make_appt()
        body = {"appointment_id": appt.pk, "scope": "appt", "body": "replay me"}
        self._post("webui:daybook_note", body)
        self._post("webui:daybook_note", body)
        self.assertEqual(
            AppointmentNote.objects.filter(appointment=appt, body="replay me").count(),
            1,
        )
        other = {"appointment_id": appt.pk, "scope": "appt", "body": "a different note"}
        self._post("webui:daybook_note", other)
        self.assertEqual(AppointmentNote.objects.filter(appointment=appt).count(), 2)

    def test_note_rejects_empty_and_unknown_scope(self):
        appt = self._make_appt()
        for payload in (
            {"appointment_id": appt.pk, "scope": "appt", "body": "  "},
            {"appointment_id": appt.pk, "scope": "visit", "body": "Hi"},
        ):
            response = self._post("webui:daybook_note", payload)
            self.assertEqual(response.status_code, 400, payload)


class ShadowStoreTests(WebuiTestBase):
    def test_daybook_loads_the_shadow_module(self):
        response = self.client.get("/")
        self.assertContains(response, "webui/shadow.js")
        self.assertContains(response, 'id="shadowState"')

    def test_shadow_assets_are_vendored(self):
        from django.contrib.staticfiles import finders

        for asset in (
            "webui/shadow.js",
            "webui/nedb/nedb_wasm.js",
            "webui/nedb/nedb_wasm_bg.wasm",
        ):
            self.assertIsNotNone(finders.find(asset), asset)


class PackTests(WebuiTestBase):
    def test_pack_carries_the_week_as_data(self):
        appt = WritePathTests._make_appt(self)
        response = self.client.get(reverse("webui:daybook_pack"), {"date": "2026-11-02"})
        data = response.json()
        self.assertTrue(data["changed"])
        self.assertEqual(data["week_of"], "2026-11-02")
        entries = data["days"]["2026-11-02"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["id"], appt.pk)
        self.assertEqual(entry["client"], "Jaime Orta")
        self.assertEqual(entry["service"], "Women's Haircut")
        self.assertEqual(entry["start_min"], 600)
        self.assertEqual(entry["end_min"], 660)
        self.assertEqual(entry["amount"], "85.00")
        self.assertEqual([s["name"] for s in data["staff"]], ["Maribel Gonzalez"])
        # Pack v2: the visit key, the rendered labels, and the
        # anchor day's ribbon/intel/agenda ride along so the
        # client can reconcile in place without a page rebuild.
        self.assertEqual(entry["visit"], entry["id"])
        self.assertEqual(entry["price_label"], "$85")
        self.assertIn("10 AM", entry["time_label"])
        self.assertEqual(data["anchor"]["ribbon"]["appointments"], 1)
        self.assertEqual(data["anchor"]["ribbon"]["revenue_label"], "$85")
        self.assertEqual(len(data["anchor"]["agenda"]), 1)
        self.assertEqual(data["anchor"]["columns"][0]["visits_count"], 1)

    def test_pack_stamp_short_circuits_until_the_world_moves(self):
        WritePathTests._make_appt(self)
        first = self.client.get(
            reverse("webui:daybook_pack"), {"date": "2026-11-02"}
        ).json()
        same = self.client.get(
            reverse("webui:daybook_pack"),
            {"date": "2026-11-02", "stamp": first["version"]},
        ).json()
        self.assertFalse(same["changed"])
        WritePathTests._make_appt(self, start_hour=12, end_hour=13)
        moved = self.client.get(
            reverse("webui:daybook_pack"),
            {"date": "2026-11-02", "stamp": first["version"]},
        ).json()
        self.assertTrue(moved["changed"])
        self.assertNotEqual(moved["version"], first["version"])


class RosterPageTests(WebuiTestBase):
    def test_roster_page_renders_the_week_matrix(self):
        response = self.client.get(reverse("webui:team"))
        self.assertContains(response, "Team &amp; Roster")
        self.assertContains(response, "Maribel Gonzalez")
        # The setUp Monday pattern (9 AM - 5 PM) shows in the matrix.
        self.assertContains(response, "9 AM – 5 PM")
        self.assertContains(response, "Patterns")

    def test_roster_add_and_delete_pattern(self):
        response = self.client.post(
            reverse("webui:team"),
            {
                "action": "add",
                "member": self.member.pk,
                "weekday": 2,
                "start": "10:00",
                "end": "14:00",
            },
        )
        self.assertEqual(response.status_code, 200)
        pattern = RosterPattern.objects.get(
            staff_member=self.member, weekday=2
        )
        self.assertEqual(pattern.start_time, datetime.time(10, 0))
        self.client.post(
            reverse("webui:team"),
            {"action": "delete", "pattern": pattern.pk},
        )
        self.assertFalse(RosterPattern.objects.filter(pk=pattern.pk).exists())


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
