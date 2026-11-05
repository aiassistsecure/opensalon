"""Tests for prior-period new-client count (service, export, command).

Synthetic fixtures only. Current window 2026-10-08..14 (7 days),
prior 2026-10-01..07; totals from new_client_count verbatim,
per-day counts bucket new_clients first-visit dates, each
current day paired with the day 7 days earlier. Count-shaped
only — no client rows or names in comparison or export.
"""
import csv, datetime, io, json, os, tempfile  # noqa: E401
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from clients.new_clients import new_client_count
from clients.prior_new_clients import prior_new_clients_report
from clients.prior_new_clients_export import (
    PRIOR_NEW_CLIENTS_FIELDNAMES, export_prior_new_clients,
    export_prior_new_clients_csv, export_prior_new_clients_dict)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
START, END = datetime.date(2026, 10, 8), datetime.date(2026, 10, 14)
PRIOR_START, PRIOR_END = datetime.date(2026, 10, 1), datetime.date(2026, 10, 7)


def at(day, hour=12):
    return datetime.datetime(2026, 10, day, hour, tzinfo=UTC)


class Base(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other = Salon.objects.create(name="Other Salon", timezone="UTC")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45)
        self._n = 0

    def _client(self, salon=None, first_visit=None):
        self._n += 1
        client = Client.objects.create(salon=salon or self.salon,
                                       first_name="Client", last_name=f"{self._n:03d}")
        if first_visit is not None:
            Appointment.objects.create(
                client=client, staff_member=self.staff, service=self.service,
                start=first_visit, end=first_visit + datetime.timedelta(minutes=45))
        return client

    def _book(self):
        # Prior Oct 1..7: 2 on Oct 1, 1 on Oct 3 -> 3. Current: 1 on Oct 8, 3 on Oct 10 -> 4.
        self._client(first_visit=at(1)); self._client(first_visit=at(1, 14))
        self._client(first_visit=at(3))
        self._client(first_visit=at(8))
        self._client(first_visit=at(10)); self._client(first_visit=at(10, 9))
        self._client(first_visit=at(10, 15))


class CoreTests(Base):
    def test_windows_totals_delta_percent_and_verbatim(self):
        self._book()
        r = prior_new_clients_report(self.salon, START, END)
        self.assertEqual((r.start_date, r.end_date), (START, END))
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_START, PRIOR_END))
        self.assertEqual(r.days, 7)
        self.assertEqual(r.current, new_client_count(self.salon, START, END))
        self.assertEqual(r.prior, new_client_count(self.salon, PRIOR_START, PRIOR_END))
        self.assertEqual((r.total.current, r.total.prior, r.total.delta,
                          r.total.percent_change), (4, 3, 1, Decimal("33.33")))
        self.assertEqual(r.count, r.total)
        self.assertEqual(r.as_dict()["total"]["percent_change"], Decimal("33.33"))

    def test_per_day_pairing_and_zero_fill(self):
        self._book()
        r = prior_new_clients_report(self.salon, START, END)
        self.assertEqual(len(r.by_day), 7)
        day8 = r.by_day[START]  # Oct 8 vs Oct 1: 1 vs 2.
        self.assertEqual((day8.current_date, day8.prior_date), (START, PRIOR_START))
        self.assertEqual((day8.current, day8.prior, day8.delta, day8.percent_change),
                         (1, 2, -1, Decimal("-50.00")))
        day10 = r.day_for(datetime.date(2026, 10, 10))  # vs Oct 3: 3 vs 1.
        self.assertEqual((day10.current, day10.prior, day10.delta, day10.percent_change),
                         (3, 1, 2, Decimal("200.00")))
        day9 = r[datetime.date(2026, 10, 9)]  # 0 vs 0 -> percent None.
        self.assertEqual((day9.current, day9.prior, day9.delta), (0, 0, 0))
        self.assertIsNone(day9.percent_change)
        self.assertEqual(sum(d.current for d in r.by_day.values()), r.total.current)
        self.assertEqual(sum(d.prior for d in r.by_day.values()), r.total.prior)

    def test_zero_prior_percent_none_and_single_day(self):
        self._client(first_visit=at(8))
        r = prior_new_clients_report(self.salon, START, START)
        self.assertEqual((r.prior_start_date, r.prior_end_date), (PRIOR_END, PRIOR_END))
        self.assertEqual((r.total.current, r.total.prior, r.total.delta), (1, 0, 1))
        self.assertIsNone(r.total.percent_change)

    def test_salon_scope_no_salon_and_not_new_if_earlier(self):
        self._book()
        self._client(salon=self.other, first_visit=at(9))
        self.assertEqual(prior_new_clients_report(self.salon, START, END).total.current, 4)
        self.assertEqual(prior_new_clients_report(self.other, START, END).total.current, 1)
        self.assertEqual(prior_new_clients_report(start_date=START, end_date=END).total.current, 5)
        veteran = self._client(first_visit=at(2))  # first visit in prior window
        Appointment.objects.create(client=veteran, staff_member=self.staff,
                                   service=self.service, start=at(9),
                                   end=at(9) + datetime.timedelta(minutes=45))
        r = prior_new_clients_report(self.salon, period_start="2026-10-08",
                                     period_end="2026-10-14")
        self.assertEqual((r.total.current, r.total.prior), (4, 4))

    def test_missing_or_reversed_raises(self):
        for call in (lambda: prior_new_clients_report(self.salon, START),
                     lambda: prior_new_clients_report(self.salon),
                     lambda: prior_new_clients_report(self.salon, END, START),
                     lambda: export_prior_new_clients_csv(self.salon, END, START)):
            with self.assertRaises(ValueError):
                call()


class ExportTests(Base):
    def test_dict_csv_agree_and_count_shaped_only(self):
        self._book()
        records = export_prior_new_clients(self.salon, START, END)
        self.assertEqual(len(records), 8)  # total + 7 days
        self.assertEqual(list(records[0]), PRIOR_NEW_CLIENTS_FIELDNAMES)
        self.assertEqual((records[0]["day"], records[0]["current_count"],
                          records[0]["prior_count"], records[0]["delta"],
                          records[0]["percent_change"]),
                         ("total", 4, 3, 1, Decimal("33.33")))
        self.assertEqual((records[1]["day"], records[1]["prior_day"]),
                         ("2026-10-08", "2026-10-01"))
        structured = export_prior_new_clients_dict(self.salon, START, END)
        self.assertEqual(structured["rows"], records)
        self.assertEqual(structured["salon_id"], self.salon.pk)
        text = export_prior_new_clients_csv(self.salon, START, END)
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual((parsed[0]["day"], parsed[0]["percent_change"]), ("total", "33.33"))
        self.assertEqual(parsed[1]["percent_change"], "-50.00")
        self.assertNotIn("Client", text)  # no client identity in the export
        self.assertFalse(any("name" in f or f == "client_id"
                             for f in PRIOR_NEW_CLIENTS_FIELDNAMES))

    def test_empty_window(self):
        records = export_prior_new_clients(self.salon, START, END)
        self.assertEqual((records[0]["current_count"], records[0]["prior_count"]), (0, 0))
        self.assertIsNone(records[0]["percent_change"])
        self.assertTrue(export_prior_new_clients_csv(self.salon, START, END).startswith(
            ",".join(PRIOR_NEW_CLIENTS_FIELDNAMES)))


class CommandTests(Base):
    def test_stdout_matches_service(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_new_clients", salon_id=self.salon.id,
                     start_date="2026-10-08", end_date="2026-10-14", stdout=out)
        self.assertEqual(out.getvalue(), export_prior_new_clients_csv(self.salon, START, END))

    def test_unknown_salon_bad_missing_and_reversed(self):
        for kwargs in (dict(salon_id=999999, start_date="2026-10-08", end_date="2026-10-14"),
                       dict(salon_id=self.salon.id, start_date="not-a-date", end_date="2026-10-14"),
                       dict(salon_id=self.salon.id),
                       dict(salon_id=self.salon.id, start_date="2026-10-14", end_date="2026-10-08")):
            with self.assertRaises(CommandError):
                call_command("export_prior_new_clients", stdout=io.StringIO(), **kwargs)


class FormatCommandTests(Base):
    def _call(self, **extra):
        out = io.StringIO()
        call_command("export_prior_new_clients", salon_id=self.salon.id,
                     start_date="2026-10-08", end_date="2026-10-14",
                     stdout=out, **extra)
        return out.getvalue()

    def test_default_format_is_csv_byte_identical(self):
        self._book()
        self.assertEqual(self._call(),
                         export_prior_new_clients_csv(self.salon, START, END))

    def test_explicit_csv_format_matches_service(self):
        self._book()
        want = export_prior_new_clients_csv(self.salon, START, END)
        self.assertEqual(self._call(format="csv"), want)
        out = io.StringIO()
        call_command("export_prior_new_clients", "--salon-id", str(self.salon.id),
                     "--start-date", "2026-10-08", "--end-date", "2026-10-14",
                     "--format", "csv", stdout=out)
        self.assertEqual(out.getvalue(), want)

    def test_json_output_matches_dict_service_rows(self):
        self._book()
        rows = export_prior_new_clients(self.salon, START, END)
        text = self._call(format="json")
        self.assertEqual(text, json.dumps(rows, indent=2,
                                          cls=DjangoJSONEncoder) + "\n")
        parsed = json.loads(text)
        self.assertEqual(len(parsed), 8)  # total + 7 days
        self.assertEqual((parsed[0]["day"], parsed[0]["current_count"],
                          parsed[0]["prior_count"], parsed[0]["delta"],
                          parsed[0]["percent_change"]),
                         ("total", 4, 3, 1, "33.33"))
        self.assertIsNone(parsed[2]["percent_change"])  # Oct 9: 0 vs 0

    def test_json_flag_matches_dict_service(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_new_clients", "--salon-id", str(self.salon.id),
                     "--start-date", "2026-10-08", "--end-date", "2026-10-14",
                     "--format", "json", stdout=out)
        self.assertEqual(out.getvalue(),
                         json.dumps(export_prior_new_clients(self.salon, START, END),
                                    indent=2, cls=DjangoJSONEncoder) + "\n")

    def test_json_composes_with_window_and_salon(self):
        self._book()
        out = io.StringIO()
        call_command("export_prior_new_clients", salon_id=self.salon.id,
                     start_date="2026-10-08", end_date="2026-10-08",
                     format="json", stdout=out)
        self.assertEqual(out.getvalue(),
                         json.dumps(export_prior_new_clients(self.salon, START, START),
                                    indent=2, cls=DjangoJSONEncoder) + "\n")
        parsed = json.loads(out.getvalue())
        self.assertEqual(len(parsed), 2)  # total + 1 day
        other = io.StringIO()
        call_command("export_prior_new_clients", salon_id=self.other.id,
                     start_date="2026-10-08", end_date="2026-10-14",
                     format="json", stdout=other)
        self.assertEqual(json.loads(other.getvalue())[0]["current_count"], 0)

    def test_json_output_file_matches_dict_service(self):
        self._book()
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior_new_clients.json")
            call_command("export_prior_new_clients", salon_id=self.salon.id,
                         start_date="2026-10-08", end_date="2026-10-14",
                         format="json", output=path, stdout=out)
            with open(path, encoding="utf-8") as fh:
                written = fh.read()
        self.assertEqual(written,
                         json.dumps(export_prior_new_clients(self.salon, START, END),
                                    indent=2, cls=DjangoJSONEncoder) + "\n")
        self.assertEqual(out.getvalue(), "")

    def test_invalid_format_raises_command_error(self):
        with self.assertRaises(CommandError):
            self._call(format="xml")
        with self.assertRaises(CommandError):
            call_command("export_prior_new_clients", "--salon-id", str(self.salon.id),
                         "--start-date", "2026-10-08", "--end-date", "2026-10-14",
                         "--format", "xml", stdout=io.StringIO())

    def test_json_reversed_range_raises(self):
        with self.assertRaises(CommandError):
            call_command("export_prior_new_clients", salon_id=self.salon.id,
                         start_date="2026-10-14", end_date="2026-10-08",
                         format="json", stdout=io.StringIO())
