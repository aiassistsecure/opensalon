import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.noshow import noshow_report
from bookings.prior_noshow import prior_noshow_report
from bookings.prior_noshow_export import (
    PRIOR_NOSHOW_EXPORT_FIELDNAMES, export_prior_noshow_csv, prior_noshow_rows)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)
PRIOR_DAY = DAY - datetime.timedelta(days=1)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 3, 12, 0, tzinfo=UTC)

def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)

class PriorNoShowTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(salon=self.salon, display_name="Stylist Two")
        self.staff3 = StaffMember.objects.create(salon=self.salon, display_name="Stylist Three")
        self.client = Client.objects.create(salon=self.salon, first_name="Test", last_name="Example")
        self.client2 = Client.objects.create(salon=self.salon, first_name="Second", last_name="Client")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(category=cat, name="Haircut", service_minutes=45)

    def _appt(self, day, hour, status, staff=None, client=None):
        return Appointment.objects.create(
            client=client or self.client, staff_member=staff or self.staff,
            service=self.service, start=at(day, hour),
            end=at(day, hour) + datetime.timedelta(minutes=45), status=status)

    def _book(self):
        NS, CP, CX = (Appointment.Status.NO_SHOW, Appointment.Status.COMPLETED,
                      Appointment.Status.CANCELLED)
        # Prior: staff1 1/2, staff2/client2 1/1 -> total 2/3.
        self._appt(PRIOR_DAY, 9, NS)
        self._appt(PRIOR_DAY, 10, CP)
        self._appt(PRIOR_DAY, 11, NS, staff=self.staff2, client=self.client2)
        # Current: staff1 2/4, staff3 1/1 -> total 3/5; cancelled excluded.
        self._appt(DAY, 9, NS); self._appt(DAY, 10, NS)
        self._appt(DAY, 11, CP); self._appt(DAY, 12, CP, client=self.client2)
        self._appt(DAY, 13, NS, staff=self.staff3)
        self._appt(DAY, 14, CX)

    def test_windows_verbatim_and_totals(self):
        self._book()
        r = prior_noshow_report(self.salon, DAY, DAY, now=NOW)
        self.assertEqual((r.start_date, r.end_date), (DAY, DAY))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_DAY, PRIOR_DAY))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current, noshow_report(self.salon, DAY, DAY, now=NOW))
        self.assertEqual(r.prior, noshow_report(self.salon, PRIOR_DAY, PRIOR_DAY, now=NOW))
        self.assertEqual((r.no_show_count.current, r.no_show_count.prior,
                          r.no_show_count.delta, r.no_show_count.percent_change),
                         (3, 2, 1, Decimal("50.00")))
        self.assertEqual((r.denominator.current, r.denominator.prior,
                          r.denominator.delta, r.denominator.percent_change),
                         (5, 3, 2, Decimal("66.67")))
        self.assertEqual((r.rate.current, r.rate.prior), (0.6, 2 / 3))
        self.assertAlmostEqual(r.rate.delta, 0.6 - 2 / 3)
        self.assertEqual(r.rate.percent_change, Decimal("-10.00"))
        d = r.as_dict()
        self.assertEqual(d["no_show_count"]["delta"], 1)
        self.assertEqual(len(d["by_staff"]), 3)
        self.assertEqual(len(d["by_client"]), 2)
        self.assertNotIn("email", str(d))

    def test_by_staff_and_by_client_unions_zero_filled(self):
        self._book()
        r = prior_noshow_report(self.salon, DAY, DAY, now=NOW)
        self.assertEqual([s.staff_name for s in r.by_staff],
                         ["Stylist One", "Stylist Three", "Stylist Two"])
        one, three, two = r.by_staff
        self.assertEqual((one.no_show_count.current, one.no_show_count.prior,
                          one.denominator.current, one.denominator.prior,
                          one.rate.current, one.rate.prior), (2, 1, 4, 2, 0.5, 0.5))
        self.assertEqual((three.no_show_count.current, three.no_show_count.prior), (1, 0))
        self.assertIsNone(three.no_show_count.percent_change)
        self.assertEqual((three.prior.no_show_count, three.prior.denominator, three.prior.rate), (0, 0, 0.0))
        self.assertEqual((two.no_show_count.current, two.denominator.current, two.rate.current), (0, 0, 0.0))
        self.assertEqual((two.no_show_count.prior, two.rate.prior, two.rate.delta), (1, 1.0, -1.0))
        self.assertEqual([c.client_name for c in r.by_client], ["Second Client", "Test Example"])
        second, test = r.by_client
        self.assertEqual((second.no_show_count.current, second.no_show_count.prior,
                          second.rate.delta), (0, 1, -1.0))
        self.assertEqual((test.no_show_count.current, test.no_show_count.prior,
                          test.denominator.current, test.denominator.prior), (3, 1, 4, 2))
        self.assertEqual(test.client_id, self.client.pk)

    def test_equal_length_aliases_empty_and_reversed(self):
        self._book()
        start = DAY - datetime.timedelta(days=6)
        r = prior_noshow_report(self.salon, start_date=start, end_date=DAY, now=NOW)
        self.assertEqual(r.days, 7)
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (start - datetime.timedelta(days=7), start - datetime.timedelta(days=1)))
        self.assertEqual(r.current, noshow_report(self.salon, start, DAY, now=NOW))
        other = Salon.objects.create(name="Other", timezone="UTC")
        empty = prior_noshow_report(other, DAY, DAY, now=NOW)
        self.assertEqual((empty.no_show_count.current, empty.no_show_count.prior,
                          empty.rate.current), (0, 0, 0.0))
        self.assertEqual((empty.by_staff, empty.by_client), ((), ()))
        with self.assertRaises(ValueError):
            prior_noshow_report(self.salon, NEXT, DAY, now=NOW)
        with self.assertRaises(ValueError):
            export_prior_noshow_csv(self.salon, NEXT, DAY, now=NOW)
        with self.assertRaises(ValueError):
            prior_noshow_report(self.salon, now=NOW)

    def test_salon_isolation(self):
        self._book()
        other = Salon.objects.create(name="Other", timezone="UTC")
        os_ = StaffMember.objects.create(salon=other, display_name="Outsider")
        oc = Client.objects.create(salon=other, first_name="O", last_name="C")
        self._appt(DAY, 9, Appointment.Status.NO_SHOW, staff=os_, client=oc)
        r = prior_noshow_report(self.salon, DAY, DAY, now=NOW)
        self.assertEqual(r.no_show_count.current, 3)
        self.assertNotIn(os_.pk, [s.staff_member_id for s in r.by_staff])
        self.assertNotIn(oc.pk, [c.client_id for c in r.by_client])

    def test_export_agreement(self):
        self._book()
        rows = prior_noshow_rows(self.salon, DAY, DAY, now=NOW)
        self.assertEqual(len(rows), 6)  # total + 3 staff + 2 client
        self.assertEqual([row["section"] for row in rows],
                         ["total", "staff", "staff", "staff", "client", "client"])
        self.assertEqual((rows[0]["current_no_show_count"], rows[0]["prior_no_show_count"],
                          rows[0]["no_show_count_delta"]), (3, 2, 1))
        self.assertEqual((rows[0]["current_rate"], rows[0]["prior_rate"]), (0.6, 2 / 3))
        text = export_prior_noshow_csv(self.salon, DAY, DAY, now=NOW)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0], PRIOR_NOSHOW_EXPORT_FIELDNAMES)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(parsed), len(rows))
        for raw, flat in zip(parsed, rows):
            for key, value in flat.items():
                if key.endswith("percent_change"):
                    expected = "" if value is None else f"{value:.2f}"
                elif key in ("current_rate", "prior_rate", "rate_delta"):
                    expected = f"{value:.4f}"
                else:
                    expected = str(value)
                self.assertEqual(raw[key], expected, key)
        three = [x for x in parsed if x["staff_name"] == "Stylist Three"][0]
        self.assertEqual(three["no_show_count_percent_change"], "")

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_noshow", salon_id=self.salon.pk, start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_noshow_csv(self.salon, DAY, DAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date=NEXT, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=DAY),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_noshow", stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch("bookings.management.commands.export_prior_noshow.open", m):
            call_command("export_prior_noshow", salon_id=self.salon.pk, start_date="2026-11-02", end_date="2026-11-02", output="out.csv")
        m().write.assert_called_once_with(export_prior_noshow_csv(self.salon, DAY, DAY))

    def test_command_with_now_matches_service(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_noshow", salon_id=self.salon.pk, start_date=DAY, end_date=DAY, now=NOW, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_noshow_csv(self.salon, DAY, DAY, now=NOW))

    def test_command_with_now_string_arg_matches_service(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_noshow", "--salon-id", str(self.salon.pk),
                     "--start-date", DAY.isoformat(), "--end-date", DAY.isoformat(),
                     "--now", NOW.isoformat(), stdout=out)
        self.assertEqual(out.getvalue(), export_prior_noshow_csv(self.salon, DAY, DAY, now=NOW))

    def test_command_now_applies_to_both_windows(self):
        self._book()
        early = datetime.datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
        out = io.StringIO()
        call_command("export_prior_noshow", salon_id=self.salon.pk, start_date=DAY, end_date=DAY, now=early, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_noshow_csv(self.salon, DAY, DAY, now=early))
        self.assertNotEqual(out.getvalue(), export_prior_noshow_csv(self.salon, DAY, DAY, now=NOW))

    def test_command_without_now_matches_service_default(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_noshow", salon_id=self.salon.pk, start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_noshow_csv(self.salon, DAY, DAY))

    def test_command_bad_now_raises_command_error(self):
        self._book()
        with self.assertRaises(CommandError):
            call_command("export_prior_noshow", salon_id=self.salon.pk, start_date=DAY, end_date=DAY, now="not-a-datetime", stdout=io.StringIO())
