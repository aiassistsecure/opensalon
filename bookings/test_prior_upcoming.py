import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.prior_upcoming import prior_upcoming_report
from bookings.prior_upcoming_export import (
    PRIOR_UPCOMING_EXPORT_FIELDNAMES, export_prior_upcoming_csv,
    export_prior_upcoming_dict)
from bookings.upcoming import upcoming_appointments
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 9)  # Monday; forward [Nov 9, Nov 12)
UTC = datetime.timezone.utc

def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)

def d(n):
    return DAY + datetime.timedelta(days=n)

class PriorUpcomingTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.one = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.two = StaffMember.objects.create(salon=self.salon, display_name="Stylist Two")
        self.three = StaffMember.objects.create(salon=self.salon, display_name="Stylist Three")
        self.four = StaffMember.objects.create(salon=self.salon, display_name="Stylist Four")
        self.client = Client.objects.create(salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(category=cat, name="Haircut", service_minutes=45)
        self.start = at(DAY, 0)

    def _appt(self, day, hour, staff=None, **kw):
        s = at(day, hour)
        return Appointment.objects.create(client=self.client, staff_member=staff or self.one, service=self.service, start=s, end=s + datetime.timedelta(minutes=45), **kw)

    def _book(self):
        # Elapsed [Nov 6, Nov 9): Nov6 One x2, Nov7 Two x1, Nov8 Three x1 = 4.
        self._appt(d(-3), 9); self._appt(d(-3), 11); self._appt(d(-2), 10, staff=self.two); self._appt(d(-1), 10, staff=self.three)
        # Forward [Nov 9, Nov 12): Nov9 One x1, Nov10 One x1 + Two x2, Nov11 Four x1 = 5.
        self._appt(d(0), 9); self._appt(d(1), 9); self._appt(d(1), 10, staff=self.two); self._appt(d(1), 13, staff=self.two); self._appt(d(2), 9, staff=self.four)
        # Decoys: cancelled forward, at forward end, before elapsed start.
        self._appt(d(0), 15, status=Appointment.Status.CANCELLED)
        self._appt(d(3), 9); self._appt(d(-4), 9)

    def test_both_windows_total_and_verbatim(self):
        self._book()
        r = prior_upcoming_report(self.salon, self.start, days=3)
        self.assertEqual((r.start, r.end), (self.start, self.start + datetime.timedelta(days=3)))
        self.assertEqual((r.elapsed_start, r.elapsed_end), (self.start - datetime.timedelta(days=3), self.start))
        self.assertEqual((r.prior_start, r.prior_end), (r.elapsed_start, r.elapsed_end))
        self.assertEqual(r.current, upcoming_appointments(self.salon, self.start, 3))
        self.assertEqual(r.prior, upcoming_appointments(self.salon, r.elapsed_start, 3))
        self.assertEqual(r.elapsed, r.prior)
        t = r.total
        self.assertEqual((t.current, t.prior, t.elapsed, t.delta, t.percent_change), (5, 4, 4, 1, Decimal("25.00")))
        self.assertEqual(r.as_dict()["total"]["elapsed"], 4)
        self.assertEqual(r.days, 3)

    def test_per_day_offset_pairs(self):
        self._book()
        r = prior_upcoming_report(self.salon, self.start, days=3)
        got = [(x.date, x.elapsed_date, x.count.current, x.count.prior, x.count.delta, x.count.percent_change) for x in r.by_day]
        self.assertEqual(got, [
            (d(0), d(-3), 1, 2, -1, Decimal("-50.00")),
            (d(1), d(-2), 3, 1, 2, Decimal("200.00")),
            (d(2), d(-1), 1, 1, 0, Decimal("0.00"))])

    def test_per_staff_union_and_prior_zero(self):
        self._book()
        r = prior_upcoming_report(self.salon, self.start, days=3)
        self.assertEqual([s.staff_name for s in r.by_staff], ["Stylist Four", "Stylist One", "Stylist Three", "Stylist Two"])
        by = {s.staff_name: s.count for s in r.by_staff}
        self.assertEqual((by["Stylist One"].current, by["Stylist One"].prior, by["Stylist One"].delta, by["Stylist One"].percent_change), (2, 2, 0, Decimal("0.00")))
        self.assertEqual((by["Stylist Two"].current, by["Stylist Two"].prior, by["Stylist Two"].delta, by["Stylist Two"].percent_change), (2, 1, 1, Decimal("100.00")))
        self.assertEqual((by["Stylist Three"].current, by["Stylist Three"].prior, by["Stylist Three"].delta), (0, 1, -1))
        self.assertEqual(by["Stylist Four"].prior, 0)
        self.assertIsNone(by["Stylist Four"].percent_change)

    def test_isolation_empty_aliases_and_errors(self):
        self._book()
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_upcoming_report(other, self.start, days=3)
        self.assertEqual((r.total.current, r.total.prior, r.total.delta), (0, 0, 0))
        self.assertIsNone(r.total.percent_change)
        self.assertEqual(r.by_staff, ())
        self.assertEqual(len(r.by_day), 3)
        self.assertEqual(prior_upcoming_report(self.salon, DAY, 3).total.current, 5)
        self.assertEqual(prior_upcoming_report(self.salon, self.start, horizon_days=3).total.current, 5)
        for args, kw in (((None, self.start), {}), ((self.salon, self.start), {"days": 0}),
                         ((self.salon, self.start), {"days": -2}), ((self.salon, self.start), {"days": "x"})):
            with self.assertRaises(ValueError):
                prior_upcoming_report(*args, **kw)

    def test_export_elapsed_labelling_and_agreement(self):
        self._book()
        text = export_prior_upcoming_csv(self.salon, self.start, 3)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0], PRIOR_UPCOMING_EXPORT_FIELDNAMES)
        self.assertIn("elapsed_count", PRIOR_UPCOMING_EXPORT_FIELDNAMES)
        self.assertNotIn("prior_count", PRIOR_UPCOMING_EXPORT_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual([x["section"] for x in rows], ["total", "day", "day", "day", "staff", "staff", "staff", "staff"])
        self.assertTrue(all(x["prior_label"] == "elapsed" for x in rows))
        self.assertEqual((rows[0]["current_count"], rows[0]["elapsed_count"], rows[0]["count_delta"], rows[0]["count_percent_change"]), ("5", "4", "1", "25.00"))
        self.assertEqual(rows[0]["elapsed_start"], (self.start - datetime.timedelta(days=3)).isoformat())
        self.assertEqual((rows[1]["date"], rows[1]["elapsed_date"]), (d(0).isoformat(), d(-3).isoformat()))
        four = [x for x in rows if x["staff_name"] == "Stylist Four"][0]
        self.assertEqual(four["count_percent_change"], "")
        data = export_prior_upcoming_dict(self.salon, self.start, 3)
        self.assertEqual(data["total"]["current"], 5)
        self.assertEqual(len(data["rows"]), len(rows))
        for dict_row, csv_row in zip(data["rows"], rows):
            self.assertEqual(str(dict_row["current_count"]), csv_row["current_count"])
            self.assertEqual(str(dict_row["elapsed_count"]), csv_row["elapsed_count"])
            self.assertEqual(dict_row["prior_label"], csv_row["prior_label"])

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_upcoming", salon_id=self.salon.pk, start=DAY, days=3, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_upcoming_csv(self.salon, DAY, 3))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start=DAY, days=3),
                       dict(salon_id=self.salon.pk, start="not-a-date", days=3),
                       dict(salon_id=self.salon.pk, start=DAY, days=0)):
            with self.assertRaises(CommandError):
                call_command("export_prior_upcoming", stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch("bookings.management.commands.export_prior_upcoming.open", m):
            call_command("export_prior_upcoming", salon_id=self.salon.pk, start="2026-11-09", days="3", output="out.csv")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertIn("elapsed", written); self.assertIn("Stylist One", written)
