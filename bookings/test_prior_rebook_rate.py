import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment
from bookings.prior_rebook_rate import prior_rebook_rate_report
from bookings.prior_rebook_rate_export import (
    PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES, export_prior_rebook_rate_csv)
from bookings.rebook_rate import rebook_rate_report
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

DAY = datetime.date(2026, 10, 26)
PRIOR_DAY = DAY - datetime.timedelta(days=1)
NEXT, LATER = DAY + datetime.timedelta(days=1), DAY + datetime.timedelta(days=14)
UTC = datetime.timezone.utc


def at(day, hour):
    return datetime.datetime.combine(day, datetime.time(hour), tzinfo=UTC)


class PriorRebookRateTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(salon=self.salon, display_name="Stylist Two")
        self.staff3 = StaffMember.objects.create(salon=self.salon, display_name="Stylist Three")
        cat = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(category=cat, name="Haircut", service_minutes=45)

    def _book(self):
        S = Appointment.Status
        # (name, day, hour, status, staff) — later rows reuse the client
        # created by an earlier row with the same name.
        rows = [
            ("P1", PRIOR_DAY, 9, S.COMPLETED, None), ("P1", LATER, 9, S.BOOKED, None),
            ("P2", PRIOR_DAY, 10, S.COMPLETED, None),
            ("P3", PRIOR_DAY, 11, S.COMPLETED, "s2"), ("P3", LATER, 11, S.COMPLETED, "s2"),
            ("P4", PRIOR_DAY, 12, S.COMPLETED, "s3"),
            ("A", DAY, 9, S.COMPLETED, None), ("A", NEXT, 9, S.BOOKED, "s2"),
            ("B", DAY, 10, S.COMPLETED, None), ("B", LATER, 10, S.CANCELLED, None),
            ("C", DAY, 11, S.COMPLETED, "s2"), ("C", LATER, 11, S.COMPLETED, "s2"),
            ("D", DAY, 12, S.BOOKED, None),
            ("E", DAY, 13, S.COMPLETED, "s2"), ("E", LATER, 13, S.NO_SHOW, "s2"),
        ]
        clients = {}
        for name, day, hour, status, staff in rows:
            if name not in clients:
                clients[name] = Client.objects.create(
                    salon=self.salon, first_name=name, last_name="Example")
            member = {"s2": self.staff2, "s3": self.staff3}.get(staff, self.staff)
            Appointment.objects.create(
                client=clients[name], staff_member=member, service=self.service,
                start=at(day, hour), end=at(day, hour) + datetime.timedelta(minutes=45),
                status=status)
        # Prior: completed 4, rebooked 2, rate 50.00.
        # Current: total 5, completed 4, rebooked 3, rate 75.00.

    def test_salon_deltas_and_windows(self):
        self._book()
        r = prior_rebook_rate_report(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.end_date), (DAY, DAY))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_DAY, PRIOR_DAY))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current, rebook_rate_report(self.salon, DAY, DAY))
        self.assertEqual(r.prior, rebook_rate_report(self.salon, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual((r.completed.current, r.completed.prior, r.completed.delta,
                          r.completed.percent_change), (4, 4, 0, Decimal("0.00")))
        self.assertEqual((r.rebooked.current, r.rebooked.prior, r.rebooked.delta,
                          r.rebooked.percent_change), (3, 2, 1, Decimal("50.00")))
        self.assertEqual((r.rebook_rate_percent.current, r.rebook_rate_percent.prior,
                          r.rebook_rate_percent.delta, r.rebook_rate_percent.percent_change),
                         (Decimal("75.00"), Decimal("50.00"), Decimal("25.00"), Decimal("50.00")))
        self.assertEqual(r.rate, r.rebook_rate_percent)
        self.assertEqual((r.current.completed, r.prior.rebooked), (4, 2))
        self.assertEqual(r.as_dict()["completed"]["delta"], 0)

    def test_per_staff_union_including_prior_only(self):
        self._book()
        r = prior_rebook_rate_report(self.salon, DAY, DAY)
        self.assertEqual([s.staff_name for s in r.by_staff],
                         ["Stylist One", "Stylist Three", "Stylist Two"])
        one, three, two = r.by_staff[0], r.by_staff[1], r.by_staff[2]
        self.assertEqual((one.completed.current, one.completed.prior,
                          one.rebook_rate_percent.current), (2, 2, Decimal("50.00")))
        self.assertEqual((two.completed.delta, two.completed.percent_change,
                          two.rebooked.delta), (1, Decimal("100.00"), 1))
        self.assertEqual((three.current.completed, three.prior.completed), (0, 1))
        self.assertIsNone(three.current_rate)
        self.assertEqual(three.prior_rate, Decimal("0.00"))
        self.assertEqual(three.completed.percent_change, Decimal("-100.00"))
        self.assertIsNone(three.rebooked.percent_change)  # zero prior
        self.assertIsNone(three.rebook_rate_percent.delta)  # current rate None

    def test_equal_length_week_and_aliases(self):
        self._book()
        start = DAY - datetime.timedelta(days=6)
        r = prior_rebook_rate_report(self.salon, start_date=start, end_date=DAY)
        self.assertEqual(r.days, 7)
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (start - datetime.timedelta(days=7), start - datetime.timedelta(days=1)))
        self.assertEqual(prior_rebook_rate_report(self.salon, DAY).completed.current, 4)

    def test_empty_and_reversed(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_rebook_rate_report(other, DAY, DAY)
        self.assertEqual((r.completed.current, r.by_staff), (0, ()))
        self.assertIsNone(r.rebook_rate_percent.current)
        self.assertIsNone(r.rebook_rate_percent.delta)
        self.assertIsNone(r.completed.percent_change)
        with self.assertRaises(ValueError):
            prior_rebook_rate_report(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            export_prior_rebook_rate_csv(self.salon, NEXT, DAY)

    def test_export_csv_total_then_per_staff(self):
        self._book()
        text = export_prior_rebook_rate_csv(self.salon, DAY, DAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_REBOOK_RATE_EXPORT_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 4)
        self.assertEqual((rows[0]["staff_member_id"], rows[0]["staff_name"]), ("", ""))
        self.assertEqual((rows[0]["current_completed"], rows[0]["prior_completed"],
                          rows[0]["current_rebook_rate_percent"], rows[0]["prior_rebook_rate_percent"],
                          rows[0]["rebook_rate_delta"], rows[0]["rebook_rate_percent_change"]),
                         ("4", "4", "75.00", "50.00", "25.00", "50.00"))
        self.assertEqual(rows[0]["prior_end_date"], PRIOR_DAY.isoformat())
        three = [x for x in rows if x["staff_name"] == "Stylist Three"][0]
        self.assertEqual(three["current_rebook_rate_percent"], "")
        self.assertEqual(three["prior_rebook_rate_percent"], "0.00")

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_rebook_rate", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(), export_prior_rebook_rate_csv(self.salon, DAY, DAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date=NEXT, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=DAY),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_rebook_rate", stdout=io.StringIO(), **kwargs)
        # Real file writes are blocked in some test sandboxes, so the
        # --output branch is verified through a mocked open.
        m = mock.mock_open()
        with mock.patch("bookings.management.commands.export_prior_rebook_rate.open", m):
            call_command("export_prior_rebook_rate", salon_id=self.salon.pk,
                         start_date="2026-10-26", end_date="2026-10-26", output="out.csv")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertIn("75.00", written)
