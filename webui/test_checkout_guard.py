"""Checkout binds to the true payload (PR-D).

The founder's report (2026-11-02): the checkout modal opened
on a $0 total against a priced visit and Complete answered
"bad payload". The chain, read in the code: a booking born in
the store carries a temporary ref until the node names it;
the rename handler passed that bare id to choose() — which
takes a block element — and threw, leaving the card
provisional; and the checkout modal armed a live sale on
whatever id it was handed, posting a NaN (JSON null) the
server can only refuse as a bad payload.

The law now: the rename re-chooses the re-painted BLOCK and
an open checkout follows the name home; the modal arms only
on a server-named id with its true payload in hand (Saving…
until then); Complete never posts an unnamed visit. The
server's own contract is unchanged and pinned below: a
non-integer appointment_id is a bad payload, a real one
settles.
"""

import datetime
import json
from decimal import Decimal
from pathlib import Path

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember


class CheckoutGuardJsTests(TestCase):
    def setUp(self):
        root = Path(__file__).parent
        self.js = (root / "static" / "webui" / "webui.js").read_text()

    def test_rename_rechoose_takes_the_block_not_the_id(self):
        self.assertNotIn("choose(d.to);", self.js)
        self.assertIn("coState.appt = d.to;", self.js)

    def test_checkout_arms_only_on_the_true_payload(self):
        self.assertIn("function armCheckout()", self.js)
        self.assertIn('"Saving…"', self.js)
        self.assertIn("payloads[coState.appt]", self.js)
        # The open modal re-arms when the payload fetch lands.
        self.assertIn("coRender();\n          armCheckout();", self.js)

    def test_complete_never_posts_an_unnamed_visit(self):
        self.assertIn(
            "This booking is still saving — give it a moment "
            "and try again.",
            self.js,
        )
        self.assertIn("!Number.isInteger(coState.appt)", self.js)


class CheckoutGuardViewTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Guard Salon", timezone="UTC")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        level = StaffLevel.objects.create(salon=self.salon, name="Senior")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana", staff_level=level
        )
        self.service = Service.objects.create(
            category=category, name="Cut", service_minutes=60
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=level,
            amount=Decimal("50.00"),
        )
        client = Client.objects.create(
            salon=self.salon, first_name="Robin", last_name="Guest"
        )
        start = timezone.now().replace(hour=10, minute=0, second=0,
                                       microsecond=0)
        self.appt = Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            service_name="Cut", start=start,
            end=start + datetime.timedelta(hours=1),
        )

    def _post(self, payload):
        return self.client.post(
            reverse("webui:daybook_checkout"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_null_appointment_id_is_a_bad_payload(self):
        # What a NaN on the client becomes in JSON — the exact
        # body behind the founder's "bad payload".
        response = self._post(
            {"appointment_id": None, "method": "cash", "products": []}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "bad payload")

    def test_temporary_ref_is_a_bad_payload(self):
        response = self._post(
            {"appointment_id": "tmp_abc123", "method": "cash",
             "products": []}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "bad payload")

    def test_real_appointment_settles(self):
        response = self._post(
            {"appointment_id": self.appt.pk, "method": "cash",
             "products": []}
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["total"], "50.00")
