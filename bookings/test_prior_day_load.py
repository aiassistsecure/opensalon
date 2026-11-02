import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.prior_day_load import prior_day_load_report
from bookings.prior_day_load_export import (
    PRIOR_DAY_LOAD_EXPORT_FIELDNAMES, export_prior_day_load_csv,
    export_prior_day_load_dict)
from bookings.staff_day import staff_day_load
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # Monday
PRIOR = DAY - datetime.timedelta(days=7)  # previous Monday
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class PriorDayLoadTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.one = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.two = StaffMember.objects.create(salon=self.salon, display_name="Stylist Two")
        self.three = StaffMember.objects.create(salon=self.salon, display_name="Stylist Three")
        self.client = Client.objects.create(salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(category=cat, name="Haircut", service_minutes=45)

    def _appt(self, day, hour, minutes, staff=None, minute=0):
        start = at(day, hour, minute)
        return Appointment.objects.create(client=self.client, staff_member=staff or self.one, service=self.service, start=start, end=start + datetime.timedelta(minutes=minutes))

    def _book(self):
        # Prior (7 days earlier): One 2/105, Two 1/60, Three none.
        self._appt(PRIOR, 9, 60); self._appt(PRIOR, 11, 45); self._appt(PRIOR, 10, 60, staff=self.two)
        # Current: One 3/165, Two none, Three 1/90.
        self._appt(DAY, 9, 45); self._appt(DAY, 13, 60); self._appt(DAY, 15, 60); self._appt(DAY, 10, 90, staff=self.three)
        # Decoy on the day before: must not count in either day.
        self._appt(DAY - datetime.timedelta(days=1), 9, 120)

    def test_deltas_offset_windows_and_verbatim(self):
        self._book()
        r = prior_day_load_report(self.salon, DAY)
        self.assertEqual(r.date, DAY); self.assertEqual(r.prior_date, PRIOR)
        self.assertEqual(r.prior_date.weekday(), DAY.weekday())
        self.assertEqual((r.start_date, r.end_date), (DAY, DAY))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR, PRIOR))
        self.assertEqual(r.current, staff_day_load(self.salon, DAY))
        self.assertEqual(r.prior, staff_day_load(self.salon, PRIOR))
        self.assertEqual((r.appointment_count.current, r.appointment_count.prior, r.appointment_count.delta, r.appointment_count.percent_change), (4, 3, 1, Decimal("33.33")))
        self.assertEqual((r.booked_minutes.current, r.booked_minutes.prior, r.booked_minutes.delta, r.booked_minutes.percent_change), (255, 165, 90, Decimal("54.55")))
        self.assertEqual((r.current_first_start, r.prior_first_start), (at(DAY, 9), at(PRIOR, 9)))
        self.assertEqual((r.current_last_start, r.prior_last_start), (at(DAY, 15), at(PRIOR, 11)))
        self.assertEqual((r.current_last_end, r.prior_last_end), (at(DAY, 16), at(PRIOR, 11, 45)))
        self.assertEqual(r.as_dict()["date"], DAY.isoformat())
        self.assertEqual(r.as_dict()["prior_date"], PRIOR.isoformat())
        self.assertEqual(r.as_dict()["booked_minutes"]["delta"], 90)

    def test_per_staff_union_and_zero_prior(self):
        self._book()
        r = prior_day_load_report(self.salon, DAY)
        self.assertEqual([s.staff_name for s in r.by_staff], ["Stylist One", "Stylist Three", "Stylist Two"])
        by = {s.staff_name: s for s in r.by_staff}
        one, two, three = by["Stylist One"], by["Stylist Two"], by["Stylist Three"]
        self.assertEqual((one.appointment_count.current, one.appointment_count.prior, one.appointment_count.delta, one.appointment_count.percent_change), (3, 2, 1, Decimal("50.00")))
        self.assertEqual((one.booked_minutes.current, one.booked_minutes.prior, one.booked_minutes.delta, one.booked_minutes.percent_change), (165, 105, 60, Decimal("57.14")))
        self.assertEqual(one.current_last_end, at(DAY, 16)); self.assertEqual(one.prior_last_end, at(PRIOR, 11, 45))
        # Zero on the missing side: Two has no current load, Three no prior.
        self.assertEqual((two.appointment_count.current, two.booked_minutes.current), (0, 0))
        self.assertIsNone(two.current_first_start)
        self.assertEqual((two.appointment_count.delta, two.appointment_count.percent_change), (-1, Decimal("-100.00")))
        self.assertEqual((three.appointment_count.prior, three.booked_minutes.prior), (0, 0))
        self.assertIsNone(three.prior_first_start)
        self.assertIsNone(three.appointment_count.percent_change); self.assertIsNone(three.booked_minutes.percent_change)
        self.assertEqual(three.current_first_start, at(DAY, 10))

    def test_aliases_empty_and_errors(self):
        self.assertEqual(prior_day_load_report(self.salon, date=DAY).date, DAY)
        self.assertEqual(prior_day_load_report(self.salon, start_date=DAY).date, DAY)
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_day_load_report(other, DAY)
        self.assertEqual((r.appointment_count.current, r.appointment_count.prior, r.appointment_count.delta), (0, 0, 0))
        self.assertIsNone(r.appointment_count.percent_change); self.assertEqual(r.by_staff, ()); self.assertIsNone(r.current_first_start)
        for args in ((None, DAY), (self.salon,), (self.salon, None), (self.salon, "not-a-date")):
            with self.assertRaises(ValueError):
                prior_day_load_report(*args)
        with self.assertRaises(ValueError):
            export_prior_day_load_csv(None, DAY)
        with self.assertRaises(ValueError):
            export_prior_day_load_csv(self.salon)

    def test_export_csv_and_dict(self):
        self._book()
        text = export_prior_day_load_csv(self.salon, DAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0], PRIOR_DAY_LOAD_EXPORT_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 4)  # total + 3 staff
        self.assertEqual((rows[0]["staff_member_id"], rows[0]["staff_name"]), ("", ""))
        self.assertEqual((rows[0]["current_appointment_count"], rows[0]["prior_appointment_count"], rows[0]["appointment_count_delta"], rows[0]["appointment_count_percent_change"]), ("4", "3", "1", "33.33"))
        self.assertEqual(rows[0]["prior_start_date"], PRIOR.isoformat())
        self.assertEqual(rows[0]["current_last_end"], at(DAY, 16).isoformat())
        self.assertEqual(rows[0]["prior_last_end"], at(PRIOR, 11, 45).isoformat())
        three = [x for x in rows if x["staff_name"] == "Stylist Three"][0]
        self.assertEqual(three["appointment_count_percent_change"], ""); self.assertEqual(three["prior_first_start"], "")
        d = export_prior_day_load_dict(self.salon, DAY)
        self.assertEqual(d["appointment_count"]["current"], 4)
        self.assertEqual(d["by_staff"][0]["staff_name"], "Stylist One")
        self.assertEqual(d["rows"][0]["appointment_count_percent_change"], Decimal("33.33"))

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_day_load", salon_id=self.salon.pk, date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_day_load_csv(self.salon, DAY))
        out2 = io.StringIO()
        call_command("export_prior_day_load", salon_id=self.salon.pk, start_date=DAY, stdout=out2)
        self.assertEqual(out2.getvalue(), out.getvalue())
        for kwargs in (dict(salon_id=self.salon.pk + 1000, date=DAY), dict(salon_id=self.salon.pk, date="not-a-date"), dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_day_load", stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch("bookings.management.commands.export_prior_day_load.open", m):
            call_command("export_prior_day_load", salon_id=self.salon.pk, date="2026-11-02", output="out.csv")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertIn("Stylist One", written)
