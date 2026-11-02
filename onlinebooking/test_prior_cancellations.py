import csv
import datetime
import io
import os
import tempfile
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from onlinebooking.cancellations import online_cancellation_summary
from onlinebooking.prior_cancellations import prior_cancellations
from onlinebooking.prior_cancellations_export import (
    EXPORT_FIELDNAMES, export_prior_cancellations,
    export_prior_cancellations_csv)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
START = datetime.date(2026, 11, 9)
END = datetime.date(2026, 11, 15)
P_START = datetime.date(2026, 11, 2)
P_END = datetime.date(2026, 11, 8)


def at(day, hour=10):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class PriorCancellationsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.alice = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        self.beth = StaffMember.objects.create(
            salon=self.salon, display_name="Beth")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Test", last_name="Example")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.cut = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        self.colour = Service.objects.create(
            category=cat, name="Colour", service_minutes=60)
        self._appt(P_START)  # prior: Alice/Haircut x1
        self._appt(START)
        self._appt(START, hour=12)
        self._appt(datetime.date(2026, 11, 10),
                   staff=self.beth, service=self.colour)
        self._appt(START, origin="phone")  # excluded everywhere

    def _appt(self, day, staff=None, service=None, origin="online",
              status="cancelled", hour=10):
        return Appointment.objects.create(
            client=self.client, staff_member=staff or self.alice,
            service=service or self.cut, start=at(day, hour),
            end=at(day, hour + 1), status=status, origin=origin)

    def test_both_windows_verbatim_and_prior_window(self):
        r = prior_cancellations(self.salon, START, END)
        self.assertEqual(r.current, online_cancellation_summary(
            self.salon, START, END))
        self.assertEqual(r.prior, online_cancellation_summary(
            self.salon, P_START, P_END))
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (P_START, P_END))
        self.assertEqual((r.start_date, r.end_date, r.days, r.previous),
                         (START, END, 7, r.prior))
        self.assertEqual(r.salon_id, self.salon.pk)

    def test_total_and_breakdown_deltas(self):
        r = prior_cancellations(self.salon, START, END)
        self.assertEqual((r.total.current, r.total.prior, r.total.delta,
                          r.total.percent_change),
                         (3, 1, 2, Decimal("200.00")))
        self.assertEqual(r.deltas, {"total": r.total})
        staff = {row.staff_name: row for row in r.by_staff}
        self.assertEqual((staff["Alice"].current, staff["Alice"].prior,
                          staff["Alice"].delta), (2, 1, 1))
        self.assertEqual((staff["Beth"].current, staff["Beth"].prior,
                          staff["Beth"].percent_change), (1, 0, None))
        svc = {row.service_name: row for row in r.by_service}
        self.assertEqual((svc["Haircut"].current, svc["Haircut"].prior),
                         (2, 1))
        self.assertEqual((svc["Colour"].current, svc["Colour"].prior), (1, 0))

    def test_by_day_offset_aligned_deltas(self):
        r = prior_cancellations(self.salon, START, END)
        self.assertEqual(len(r.by_day), 7)
        self.assertEqual(r.by_date, r.by_day)
        self.assertEqual([d.offset for d in r.by_day], list(range(7)))
        self.assertEqual([d.date for d in r.by_day],
                         [START + datetime.timedelta(days=i)
                          for i in range(7)])
        self.assertEqual([d.prior_date for d in r.by_day],
                         [P_START + datetime.timedelta(days=i)
                          for i in range(7)])
        # Verbatim from the source tuples, offset-aligned.
        self.assertEqual([d.current for d in r.by_day],
                         [row.count for row in r.current.by_day])
        self.assertEqual([d.prior for d in r.by_day],
                         [row.count for row in r.prior.by_day])
        first, second = r.by_day[0], r.by_day[1]
        self.assertEqual((first.current, first.prior, first.delta,
                          first.percent_change),
                         (2, 1, 1, Decimal("100.00")))
        self.assertEqual((second.current, second.prior, second.delta),
                         (1, 0, 1))
        self.assertIsNone(second.percent_change)
        self.assertTrue(all(
            (d.current, d.prior, d.delta) == (0, 0, 0)
            for d in r.by_day[2:]))
        self.assertEqual(sum(d.current for d in r.by_day), r.total.current)
        self.assertEqual(sum(d.prior for d in r.by_day), r.total.prior)
        self.assertEqual(first.as_dict()["date"], START.isoformat())
        self.assertEqual(first.as_dict()["prior_date"],
                         P_START.isoformat())

    def test_by_day_zero_filled_for_empty_salon(self):
        other = Salon.objects.create(name="Fresh", timezone="UTC")
        r = prior_cancellations(other, START, END)
        self.assertEqual(len(r.by_day), 7)
        self.assertTrue(all(
            (d.current, d.prior, d.delta, d.percent_change)
            == (0, 0, 0, None) for d in r.by_day))

    def test_percent_change_none_when_prior_zero(self):
        other = Salon.objects.create(name="Fresh", timezone="UTC")
        r = prior_cancellations(other, START, END)
        self.assertEqual((r.total.current, r.total.prior, r.total.delta), (0, 0, 0))
        self.assertIsNone(r.total.percent_change)
        self.assertEqual((r.by_staff, r.by_service), ((), ()))

    def test_aliases_and_errors(self):
        self.assertEqual(prior_cancellations(
            self.salon, start_date=START, end_date=END).total.current, 3)
        self.assertEqual(prior_cancellations(
            self.salon, "2026-11-09", "2026-11-15").total.current, 3)
        with self.assertRaises(ValueError):
            prior_cancellations(self.salon, END, START)
        with self.assertRaises(ValueError):
            prior_cancellations(None, START, END)
        with self.assertRaises(ValueError):
            prior_cancellations(self.salon, START)
        with self.assertRaises(TypeError):
            prior_cancellations(self.salon, START, END, bogus=1)


class PriorCancellationsExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        staff = StaffMember.objects.create(
            salon=self.salon, display_name="Alice")
        client = Client.objects.create(
            salon=self.salon, first_name="T", last_name="E")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        svc = Service.objects.create(
            category=cat, name="Haircut", service_minutes=60)
        for day in (P_START, START):
            Appointment.objects.create(
                client=client, staff_member=staff, service=svc,
                start=at(day), end=at(day, 11),
                status="cancelled", origin="online")

    def test_rows_and_csv_agree(self):
        rows = export_prior_cancellations(self.salon, START, END)
        self.assertEqual([r["section"] for r in rows],
                         ["total", "staff", "service"] + ["day"] * 7)
        self.assertTrue(all(list(r) == EXPORT_FIELDNAMES for r in rows))
        self.assertEqual((rows[0]["current"], rows[0]["prior"],
                          rows[0]["delta"], rows[0]["percent_change"]),
                         (1, 1, 0, "0.00"))
        self.assertEqual(rows[0]["prior_start_date"], P_START.isoformat())
        parsed = list(csv.DictReader(io.StringIO(
            export_prior_cancellations_csv(self.salon, START, END))))
        self.assertEqual(parsed, [{k: "" if v is None else str(v)
                                   for k, v in r.items()} for r in rows])

    def test_day_rows_carry_offset_aligned_pair(self):
        rows = export_prior_cancellations(self.salon, START, END)
        days = [r for r in rows if r["section"] == "day"]
        self.assertEqual(len(days), 7)
        self.assertEqual(
            (days[0]["date"], days[0]["prior_date"], days[0]["current"],
             days[0]["prior"], days[0]["delta"],
             days[0]["percent_change"]),
            (START.isoformat(), P_START.isoformat(), 1, 1, 0, "0.00"))
        self.assertTrue(all(
            (r["current"], r["prior"], r["delta"]) == (0, 0, 0)
            for r in days[1:]))
        self.assertTrue(all(
            r["date"] is None and r["prior_date"] is None
            for r in rows if r["section"] != "day"))

    def test_command_stdout_file_and_errors(self):
        out = io.StringIO()
        call_command("export_prior_cancellations",
                     "--salon-id", str(self.salon.pk),
                     "--start-date", START.isoformat(),
                     "--end-date", END.isoformat(), stdout=out)
        self.assertEqual(out.getvalue(), export_prior_cancellations_csv(
            self.salon, START, END))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior.csv")
            call_command("export_prior_cancellations", salon_id=self.salon.pk,
                         start_date=START, end_date=END, output=path)
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), out.getvalue())
        for kwargs in ({"salon_id": 99999, "start_date": START, "end_date": END},
                       {"salon_id": self.salon.pk},
                       {"salon_id": self.salon.pk, "start_date": "bad",
                        "end_date": END},
                       {"salon_id": self.salon.pk, "start_date": END,
                        "end_date": START}):
            with self.assertRaises(CommandError):
                call_command("export_prior_cancellations", **kwargs)
