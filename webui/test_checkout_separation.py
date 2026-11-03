"""Check-in and checkout are separate doors (founder, 2026-11-02,
re-asserted 2026-11-03: "check in still connects to check out").

The plumbing was separated first — a status flip never settles a
visit — but the rail still stacked one big gradient Checkout
button directly under the Check In button, offered from the
moment of booking. That is the connection the desk felt. The
law now: the rail's till exists only once the visit is IN
SERVICE, in its own Till section behind a divider. Arrival
(booked / confirmed / arrived) offers arrival actions only;
settling early remains possible at the POS, never tangled
into the arrival card.
"""
import datetime
from decimal import Decimal
from pathlib import Path

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client as SalonClient
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

CHECKOUT_BTN = "data-checkout data-appt="


class RailSeparationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(name="Mint", timezone="UTC")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        level = StaffLevel.objects.create(salon=self.salon, name="Senior")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana", staff_level=level
        )
        self.service = Service.objects.create(
            category=category, name="Cut", service_minutes=60
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=level, amount=Decimal("50.00")
        )
        self.guest = SalonClient.objects.create(
            salon=self.salon, first_name="Robin", last_name="Guest"
        )
        self.daybook_url = reverse("webui:daybook")

    def _book(self, status):
        start = timezone.now().replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        return Appointment.objects.create(
            client=self.guest,
            staff_member=self.staff,
            service=self.service,
            service_name="Cut",
            start=start,
            end=start + datetime.timedelta(hours=1),
            status=status,
        )

    def _page(self):
        return self.client.get(self.daybook_url).content.decode()

    def test_booked_rail_has_no_checkout_button(self):
        self._book("booked")
        self.assertNotIn(CHECKOUT_BTN, self._page())

    def test_arrived_rail_has_no_checkout_button(self):
        self._book("arrived")
        self.assertNotIn(CHECKOUT_BTN, self._page())

    def test_in_service_rail_has_the_till(self):
        self._book("in_service")
        page = self._page()
        self.assertIn(CHECKOUT_BTN, page)
        self.assertIn("rail-till", page)
        self.assertIn("Checkout · $50", page)

    def test_completed_rail_has_no_checkout_button(self):
        self._book("completed")
        self.assertNotIn(CHECKOUT_BTN, self._page())


class RailSeparationJsTests(TestCase):
    def setUp(self):
        root = Path(__file__).parent
        self.js = (root / "static" / "webui" / "webui.js").read_text()
        self.main_html = (
            root / "templates" / "webui" / "_daybook_main.html"
        ).read_text()

    def test_client_rail_gates_checkout_to_in_service(self):
        self.assertIn('d.status === "in_service" && d.stack_price_label', self.js)
        self.assertNotIn(
            '["booked", "confirmed", "arrived", "in_service"].indexOf(d.status)',
            self.js,
        )
        self.assertIn("rail-till", self.js)

    def test_no_click_can_climb_to_a_checkout_that_is_not_there(self):
        # The toggle bug: the rail handler matched a bare
        # [data-checkout], and closest() climbed from the
        # check-in toggle to the page layout, which carried
        # the checkout endpoint under the same attribute name
        # — so a check-in click "found" a checkout button and
        # launched the modal with no appointment named. The
        # match now names the button itself, and the endpoint
        # lives under its own attribute.
        self.assertIn('closest("button[data-checkout]")', self.js)
        self.assertNotIn('closest("[data-checkout]")', self.js)
        self.assertIn("layout.dataset.checkoutUrl", self.js)
        self.assertNotIn("layout.dataset.checkout,", self.js)
        self.assertIn("data-checkout-url=", self.main_html)
        self.assertNotIn('data-checkout="', self.main_html)
