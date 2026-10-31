"""Block legibility: no text is ever drawn over other text.

The founder's screenshot of 2026-10-31: prices floated absolute
at the block's bottom-right, on top of the service line on a
60-minute block and on top of the client's name on a 30-minute
one. The geometry law that replaced it: the block is a flex
column; the price rides the name row in flow (the name
ellipsizes first); the service band flexes away inside its own
band; mini keeps one row — name + price; micro keeps the name.
"""
import datetime
from decimal import Decimal

from django.contrib.staticfiles import finders
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
from team.models import RosterPattern, StaffMember


class BlockLegibilityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.salon = Salon.objects.create(name="Mint On The Avenue")
        self.level = StaffLevel.objects.create(
            name="Level 6", salon=self.salon
        )
        category = ServiceCategory.objects.create(
            name="Hair", salon=self.salon
        )
        self.service = Service.objects.create(
            name="Women's Haircut", category=category, service_minutes=60
        )
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"),
        )
        self.member = StaffMember.objects.create(
            display_name="Maribel Gonzalez", salon=self.salon,
            staff_level=self.level,
        )
        RosterPattern.objects.create(
            staff_member=self.member,
            weekday=RosterPattern.Weekday.MONDAY,
            start_time=datetime.time(9, 0),
            end_time=datetime.time(17, 0),
        )
        self.person = SalonClient.objects.create(
            salon=self.salon, first_name="Jaime", last_name="Orta",
            phone="407-555-0100",
        )

    def _appt(self, start_h, start_m, end_h, end_m):
        start = timezone.make_aware(
            datetime.datetime(2026, 11, 2, start_h, start_m)
        )
        end = timezone.make_aware(
            datetime.datetime(2026, 11, 2, end_h, end_m)
        )
        return Appointment.objects.create(
            client=self.person,
            staff_member=self.member, service=self.service,
            start=start, end=end, status="booked",
        )

    def test_price_rides_the_name_row_in_the_markup(self):
        self._appt(10, 0, 11, 0)
        html = self.client.get(
            reverse("webui:daybook"), {"date": "2026-11-02"}
        ).content.decode()
        # One row, in flow: client first, the service's inline
        # fine print beside it (shown on the shortest blocks),
        # price after — the exact structure the stylesheet lays
        # out without overlap.
        self.assertIn(
            '<div class="b-main"><div class="b-client">Jaime Orta</div>'
            '<span class="b-svc-inline">Women&#x27;s Haircut</span>'
            '<div class="b-price">$85</div></div>',
            html,
        )

    def test_stylesheet_never_positions_the_price_over_text(self):
        path = finders.find("webui/webui.css")
        with open(path, encoding="utf-8") as handle:
            css = handle.read()
        block_rule = css[css.index(".appt-block {"):css.index("}", css.index(".appt-block {"))]
        self.assertIn("display: flex", block_rule)
        self.assertIn("flex-direction: column", block_rule)
        price_rule = css[css.index(".b-price {"):css.index("}", css.index(".b-price {"))]
        self.assertNotIn("position: absolute", price_rule)
        self.assertNotIn("position:absolute", price_rule)
        # The service band is the shock absorber: it flexes and
        # clips inside itself instead of being covered.
        self.assertIn(".b-services { flex: 0 1 auto; min-height: 0;", css)
        # Mini yields the time row only — the service is never
        # spent (the founder's fine-print law): it stays under
        # the name at one clamped fine-print line.
        self.assertIn(
            ".appt-block.mini .b-top { display: none; }",
            css,
        )
        self.assertNotIn(
            ".appt-block.mini .b-top, .appt-block.mini .b-services "
            "{ display: none; }",
            css,
        )
