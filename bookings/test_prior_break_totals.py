import csv, datetime, io  # noqa: E401
from decimal import Decimal
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.break_totals import break_totals
from bookings.models import Break
from bookings.prior_break_totals import prior_break_totals_report
from bookings.prior_break_totals_export import (
    PRIOR_BREAK_TOTALS_EXPORT_FIELDNAMES, export_prior_break_totals_csv,
    export_prior_break_totals_dict)
from saloncore.models import Salon
from team.models import StaffMember

DAY = datetime.date(2026, 11, 2)  # Monday, current window
PRIOR_DAY = DAY - datetime.timedelta(days=1)
NEXT = DAY + datetime.timedelta(days=1)
UTC = datetime.timezone.utc


def at(day, hour, minute=0):
    return datetime.datetime.combine(day, datetime.time(hour, minute), tzinfo=UTC)


class PriorBreakTotalsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example", timezone="UTC")
        self.staff = StaffMember.objects.create(salon=self.salon, display_name="Stylist One")
        self.staff2 = StaffMember.objects.create(salon=self.salon, display_name="Stylist Two")
        self.staff3 = StaffMember.objects.create(salon=self.salon, display_name="Stylist Three")

    def _break(self, day, hour, minutes, paid=False, staff=None):
        start = at(day, hour)
        return Break.objects.create(staff_member=staff or self.staff, start=start,
            end=start + datetime.timedelta(minutes=minutes), paid=paid)

    def _book(self):
        # Prior: One paid 30 + unpaid 60; Two none.
        self._break(PRIOR_DAY, 12, 30, paid=True)
        self._break(PRIOR_DAY, 13, 60, paid=False)
        # Current: One paid 45 + unpaid 15; Two unpaid 20; Three none.
        self._break(DAY, 12, 45, paid=True)
        self._break(DAY, 13, 15, paid=False)
        self._break(DAY, 12, 20, paid=False, staff=self.staff2)

    def test_salon_deltas_windows_and_verbatim(self):
        self._book()
        r = prior_break_totals_report(self.salon, DAY, DAY)
        self.assertEqual((r.start_date, r.end_date), (DAY, DAY))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_DAY, PRIOR_DAY))
        self.assertEqual(r.days, 1)
        self.assertEqual(r.current, break_totals(self.salon, DAY, DAY))
        self.assertEqual(r.prior, break_totals(self.salon, PRIOR_DAY, PRIOR_DAY))
        self.assertEqual((r.break_count.current, r.break_count.prior,
                          r.break_count.delta, r.break_count.percent_change),
                         (3, 2, 1, Decimal("50.00")))
        self.assertEqual((r.total_break_minutes.current, r.total_break_minutes.prior,
                          r.total_break_minutes.delta,
                          r.total_break_minutes.percent_change),
                         (80, 90, -10, Decimal("-11.11")))
        self.assertEqual((r.paid_minutes.current, r.paid_minutes.prior,
                          r.paid_minutes.delta, r.paid_minutes.percent_change),
                         (45, 30, 15, Decimal("50.00")))
        self.assertEqual((r.unpaid_minutes.current, r.unpaid_minutes.prior,
                          r.unpaid_minutes.delta), (35, 60, -25))
        self.assertEqual(r.paid_break_count.percent_change, Decimal("0.00"))
        self.assertEqual(r.as_dict()["break_count"]["delta"], 1)
        self.assertEqual(r.as_dict()["by_staff"][0]["staff_name"], "Stylist One")

    def test_per_staff_union_and_zero_prior(self):
        self._book()
        r = prior_break_totals_report(self.salon, DAY, DAY)
        self.assertEqual([s.staff_name for s in r.by_staff],
                         ["Stylist One", "Stylist Two"])
        one, two = r.by_staff
        self.assertEqual((one.break_count.current, one.break_count.prior), (2, 2))
        self.assertEqual((one.paid_minutes.current, one.paid_minutes.prior), (45, 30))
        self.assertEqual((two.break_count.current, two.break_count.prior), (1, 0))
        self.assertIsNone(two.break_count.percent_change)  # zero prior
        self.assertIsNone(two.unpaid_minutes.percent_change)
        self.assertEqual(two.current.break_count, 1)
        self.assertEqual(two.prior.break_count, 0)
        scoped = prior_break_totals_report(self.salon, DAY, DAY, staff_member=self.staff2)
        self.assertEqual([s.staff_member_id for s in scoped.by_staff],
                         [self.staff2.pk])
        self.assertEqual(scoped.break_count.current, 1)

    def test_equal_length_week_and_aliases(self):
        self._book()
        start = DAY - datetime.timedelta(days=6)
        r = prior_break_totals_report(self.salon, start_date=start, end_date=DAY)
        self.assertEqual(r.days, 7)
        self.assertEqual((r.prior_start_date, r.prior_end_date),
                         (start - datetime.timedelta(days=7),
                          start - datetime.timedelta(days=1)))
        self.assertEqual(prior_break_totals_report(self.salon, DAY).break_count.current, 3)

    def test_empty_and_reversed(self):
        other = Salon.objects.create(name="Other", timezone="UTC")
        r = prior_break_totals_report(other, DAY, DAY)
        self.assertEqual((r.break_count.current, r.break_count.prior, r.break_count.delta), (0, 0, 0))
        self.assertIsNone(r.break_count.percent_change)
        self.assertEqual(r.by_staff, ())
        with self.assertRaises(ValueError):
            prior_break_totals_report(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            export_prior_break_totals_csv(self.salon, NEXT, DAY)
        with self.assertRaises(ValueError):
            prior_break_totals_report(self.salon)

    def test_export_csv_and_dict(self):
        self._book()
        text = export_prior_break_totals_csv(self.salon, DAY, DAY)
        self.assertEqual(list(csv.reader(io.StringIO(text)))[0],
                         PRIOR_BREAK_TOTALS_EXPORT_FIELDNAMES)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 3)  # total + 2 staff
        self.assertEqual((rows[0]["staff_member_id"], rows[0]["staff_name"]), ("", ""))
        self.assertEqual((rows[0]["current_break_count"], rows[0]["prior_break_count"],
                          rows[0]["break_count_delta"],
                          rows[0]["break_count_percent_change"]),
                         ("3", "2", "1", "50.00"))
        self.assertEqual(rows[0]["prior_end_date"], PRIOR_DAY.isoformat())
        two = [x for x in rows if x["staff_name"] == "Stylist Two"][0]
        self.assertEqual(two["break_count_percent_change"], "")
        d = export_prior_break_totals_dict(self.salon, DAY, DAY)
        self.assertEqual(d["break_count"]["current"], 3)
        self.assertEqual(d["by_staff"][1]["staff_name"], "Stylist Two")
        self.assertEqual(d["rows"][0]["break_count_percent_change"], Decimal("50.00"))

    def test_command_stdout_file_and_errors(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_break_totals", salon_id=self.salon.pk,
                     start_date=DAY, end_date=DAY, stdout=out)
        self.assertEqual(out.getvalue(),
                         export_prior_break_totals_csv(self.salon, DAY, DAY))
        for kwargs in (dict(salon_id=self.salon.pk + 1000, start_date=DAY, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date=NEXT, end_date=DAY),
                       dict(salon_id=self.salon.pk, start_date="not-a-date", end_date=DAY),
                       dict(salon_id=self.salon.pk)):
            with self.assertRaises(CommandError):
                call_command("export_prior_break_totals", stdout=io.StringIO(), **kwargs)
        m = mock.mock_open()
        with mock.patch("bookings.management.commands.export_prior_break_totals.open", m):
            call_command("export_prior_break_totals", salon_id=self.salon.pk,
                         start_date="2026-11-02", end_date="2026-11-02",
                         output="out.csv")
        written = "".join(c.args[0] for c in m().write.call_args_list)
        self.assertIn("Stylist One", written)
