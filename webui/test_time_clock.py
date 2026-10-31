"""The time clock: PINs, standing, and the one opposite action.

The clock Mark specced 2026-10-31: a clock bottom-left of every
page; tap it, enter a PIN; the PIN names exactly one person
(manager-set, unique per salon, deduped on save); a valid PIN shows
that person's standing — clocked in or out — and offers the one
opposite action. Standing derives from the AttendanceRecord event
log, the same law the rest of the app reads.
"""
import json

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from saloncore.models import Salon
from team.models import AttendanceRecord, StaffMember


class TimeClockTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(
            name="Mint", timezone="America/New_York"
        )
        self.dawn = StaffMember.objects.create(
            salon=self.salon, display_name="Dawn Davalos", pin="101985"
        )
        self.eva = StaffMember.objects.create(
            salon=self.salon, display_name="Eva Bonilla"
        )
        self.status_url = reverse("webui:clock_status")
        self.toggle_url = reverse("webui:clock_toggle")
        self.team_url = reverse("webui:team")

    def post_pin(self, url, pin):
        return self.client.post(
            url,
            data=json.dumps({"pin": pin}),
            content_type="application/json",
        )

    # -- the PIN itself -------------------------------------------------

    def test_duplicate_pin_in_one_salon_is_rejected_on_save(self):
        with self.assertRaises(ValidationError):
            StaffMember(
                salon=self.salon, display_name="Copy", pin="101985"
            ).full_clean()

    def test_same_pin_in_another_salon_is_fine(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        StaffMember.objects.create(
            salon=other, display_name="Elsewhere", pin="101985"
        )

    def test_blank_pins_coexist(self):
        StaffMember.objects.create(salon=self.salon, display_name="No Pin A")
        StaffMember.objects.create(salon=self.salon, display_name="No Pin B")

    # -- status ----------------------------------------------------------

    def test_wrong_pin_gets_one_generic_refusal(self):
        resp = self.post_pin(self.status_url, "999999")
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertFalse(body["ok"])
        self.assertNotIn("Dawn", body["error"])

    def test_blank_pin_never_matches_a_member_without_one(self):
        resp = self.post_pin(self.status_url, "")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])

    def test_valid_pin_reports_clocked_out_and_offers_clock_in(self):
        resp = self.post_pin(self.status_url, "101985")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["member"], "Dawn Davalos")
        self.assertFalse(body["clocked_in"])
        self.assertEqual(body["action"], "Clock in")

    def test_valid_pin_reports_clocked_in_since(self):
        AttendanceRecord.objects.create(
            staff_member=self.dawn,
            event_type=AttendanceRecord.EventType.CHECK_IN,
        )
        body = self.post_pin(self.status_url, "101985").json()
        self.assertTrue(body["clocked_in"])
        self.assertIsNotNone(body["since"])
        self.assertEqual(body["action"], "Clock out")

    # -- toggle ----------------------------------------------------------

    def test_toggle_clocks_in_then_out_on_the_event_log(self):
        body = self.post_pin(self.toggle_url, "101985").json()
        self.assertTrue(body["clocked_in"])
        self.assertEqual(body["just"], "in")
        self.assertEqual(
            self.dawn.attendance_records.first().event_type,
            AttendanceRecord.EventType.CHECK_IN,
        )
        body = self.post_pin(self.toggle_url, "101985").json()
        self.assertFalse(body["clocked_in"])
        self.assertEqual(body["just"], "out")
        self.assertEqual(
            self.dawn.attendance_records.first().event_type,
            AttendanceRecord.EventType.CHECK_OUT,
        )

    def test_toggle_with_wrong_pin_records_nothing(self):
        resp = self.post_pin(self.toggle_url, "424242")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    # -- manager sets PINs on the Team page ------------------------------

    def test_manager_sets_a_pin(self):
        resp = self.client.post(
            self.team_url,
            {"action": "set_pin", "member": self.eva.pk, "pin": "071990"},
        )
        self.assertIn("PIN set for Eva Bonilla", resp.content.decode())
        self.eva.refresh_from_db()
        self.assertEqual(self.eva.pin, "071990")

    def test_manager_cannot_hand_out_a_pin_already_in_use(self):
        resp = self.client.post(
            self.team_url,
            {"action": "set_pin", "member": self.eva.pk, "pin": "101985"},
        )
        html = resp.content.decode()
        self.assertIn("already Dawn Davalos", html)
        self.assertIn("every PIN has to be unique", html)
        self.eva.refresh_from_db()
        self.assertEqual(self.eva.pin, "")

    def test_manager_rejects_a_non_digit_pin(self):
        resp = self.client.post(
            self.team_url,
            {"action": "set_pin", "member": self.eva.pk, "pin": "abcd"},
        )
        self.assertIn("4 to 8 digits", resp.content.decode())
        self.eva.refresh_from_db()
        self.assertEqual(self.eva.pin, "")

    def test_manager_clears_a_pin(self):
        resp = self.client.post(
            self.team_url,
            {"action": "set_pin", "member": self.dawn.pk, "pin": ""},
        )
        self.assertIn("PIN is cleared", resp.content.decode())
        self.dawn.refresh_from_db()
        self.assertEqual(self.dawn.pin, "")

    def test_team_page_never_prints_a_pin(self):
        html = self.client.get(self.team_url).content.decode()
        self.assertIn("Time clock PINs", html)
        self.assertIn("PIN set", html)
        self.assertNotIn("101985", html)

    # -- the shell --------------------------------------------------------

    def test_every_page_carries_the_clock(self):
        html = self.client.get(reverse("webui:daybook")).content.decode()
        self.assertIn('id="clockCard"', html)
        self.assertIn('id="clockModal"', html)
        self.assertIn('data-tz="America/New_York"', html)
