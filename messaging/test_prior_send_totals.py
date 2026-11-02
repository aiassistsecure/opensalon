import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from messaging.campaign_send_totals import campaign_send_totals
from messaging.models import Campaign, CampaignSend, ReminderSend
from messaging.prior_send_totals import prior_send_totals
from messaging.prior_send_totals_export import (
    PRIOR_SEND_TOTALS_FIELDNAMES, export_prior_send_totals_csv)
from messaging.send_totals import send_totals
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
P1 = datetime.date(2026, 3, 1)
P2 = datetime.date(2026, 3, 2)
C1 = datetime.date(2026, 3, 3)
C2 = datetime.date(2026, 3, 4)

def at(day, hour=12):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)

class PriorSendTotalsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.other = Salon.objects.create(name="Other", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.other_staff = StaffMember.objects.create(
            salon=self.other, display_name="Other Stylist")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=cat, name="Haircut", service_minutes=45)
        self._n = 0

    def _client(self, salon):
        self._n += 1
        return Client.objects.create(
            salon=salon, first_name=f"C{self._n}", last_name="Example",
            email=f"c{self._n}@example.com", sms_opt_in=True, email_opt_in=True)

    def _reminder(self, salon, staff, channel, when):
        client = self._client(salon)
        start = timezone.now() + datetime.timedelta(days=1)
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=self.service,
            start=start, end=start + datetime.timedelta(minutes=45),
            status=Appointment.Status.BOOKED)
        return ReminderSend.objects.create(
            appointment=appt, client=client, channel=channel,
            status="sent", sent_at=when)

    def _campaign(self, salon, channel, when):
        client = self._client(salon)
        self._n += 1
        campaign = Campaign.objects.create(
            salon=salon, name=f"Campaign {self._n}", channel=channel,
            body="Hello", status=Campaign.Status.SENT, sent_at=when)
        return CampaignSend.objects.create(
            campaign=campaign, client=client, channel=channel,
            status="sent", sent_at=when)

    def _book(self):
        # Prior (P1-P2): reminder email 1, sms 1; campaign email 1.
        self._reminder(self.salon, self.staff, "email", at(P1, 9))
        self._reminder(self.salon, self.staff, "sms", at(P2, 9))
        self._campaign(self.salon, "email", at(P2, 10))
        # Current (C1-C2): reminder email 2, sms 1; campaign sms 2.
        self._reminder(self.salon, self.staff, "email", at(C1, 9))
        self._reminder(self.salon, self.staff, "email", at(C1, 10))
        self._reminder(self.salon, self.staff, "sms", at(C2, 9))
        self._campaign(self.salon, "sms", at(C1, 11))
        self._campaign(self.salon, "sms", at(C1, 12))
        # Other salon in current window: never counted.
        self._reminder(self.other, self.other_staff, "email", at(C1, 9))
        self._campaign(self.other, "email", at(C1, 9))

    def test_both_windows_verbatim_and_deltas(self):
        self._book()
        r = prior_send_totals(self.salon, C1, C2)
        self.assertEqual((r.start_date, r.end_date), (C1, C2))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (P1, P2))
        self.assertEqual(r.days, 2)
        self.assertEqual(r.current_reminder, send_totals(self.salon, C1, C2))
        self.assertEqual(r.prior_reminder, send_totals(self.salon, P1, P2))
        self.assertEqual(r.current_campaign,
                         campaign_send_totals(self.salon, C1, C2))
        self.assertEqual(r.prior_campaign,
                         campaign_send_totals(self.salon, P1, P2))
        self.assertEqual((r.total.current, r.total.prior, r.total.delta,
                          r.total.percent_change),
                         (5, 3, 2, Decimal("66.67")))
        self.assertEqual((r.reminder_total.current, r.reminder_total.prior,
                          r.reminder_total.delta,
                          r.reminder_total.percent_change),
                         (3, 2, 1, Decimal("50.00")))
        self.assertEqual((r.campaign_total.current, r.campaign_total.prior,
                          r.campaign_total.delta,
                          r.campaign_total.percent_change),
                         (2, 1, 1, Decimal("100.00")))
        self.assertEqual((r.reminder_by_channel["email"].current,
                          r.reminder_by_channel["email"].prior), (2, 1))
        self.assertEqual((r.combined_by_channel["sms"].current,
                          r.combined_by_channel["sms"].prior,
                          r.combined_by_channel["sms"].delta), (3, 1, 2))
        self.assertEqual(r.combined_by_channel["email"].delta, 0)
        self.assertEqual(r.as_dict()["total"]["delta"], 2)

    def test_zero_prior_percent_none_and_empty(self):
        r = prior_send_totals(self.salon, C1, C2)
        self.assertEqual((r.total.current, r.total.prior), (0, 0))
        self.assertIsNone(r.total.percent_change)
        self._book()
        # Window before any data: current is the prior book, prior empty.
        r2 = prior_send_totals(self.salon, P1, P2)
        self.assertEqual(r2.reminder_total.prior, 0)
        self.assertIsNone(r2.reminder_total.percent_change)

    def test_aliases_single_day_and_reversed(self):
        self._book()
        r = prior_send_totals(self.salon, date_from=C1, date_to=C2)
        self.assertEqual(r.total.current, 5)
        single = prior_send_totals(self.salon, C1)
        self.assertEqual((single.prior_start_date, single.prior_end_date),
                         (P2, P2))
        with self.assertRaises(ValueError):
            prior_send_totals(self.salon, C2, C1)
        with self.assertRaises(ValueError):
            prior_send_totals(None, C1, C2)
        with self.assertRaises(ValueError):
            export_prior_send_totals_csv(self.salon, C2, C1)

    def test_export_csv(self):
        self._book()
        text = export_prior_send_totals_csv(self.salon, C1, C2)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_SEND_TOTALS_FIELDNAMES)
        rows = {row["metric"]: row
                for row in csv.DictReader(io.StringIO(text))}
        self.assertEqual((rows["total"]["current"], rows["total"]["prior"],
                          rows["total"]["delta"],
                          rows["total"]["percent_change"]),
                         ("5", "3", "2", "66.67"))
        self.assertEqual(rows["campaign_sms"]["current"], "2")
        self.assertEqual(rows["total"]["prior_start_date"], P1.isoformat())
        self.assertIn("combined_email", rows)

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_send_totals", salon_id=self.salon.pk,
                     start_date=C1, end_date=C2, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_send_totals_csv(self.salon, C1, C2))
        for kwargs in (dict(salon_id=self.salon.pk + 1000,
                            start_date=C1, end_date=C2),
                       dict(salon_id=self.salon.pk,
                            start_date=C2, end_date=C1),
                       dict(salon_id=self.salon.pk,
                            start_date="not-a-date", end_date=C2),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_send_totals",
                             stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch(
                "messaging.management.commands.export_prior_send_totals.open", m):
            call_command("export_prior_send_totals", salon_id=self.salon.pk,
                         start_date="2026-03-03", end_date="2026-03-04",
                         output="out.csv")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertIn("66.67", written)
