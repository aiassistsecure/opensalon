import csv
import datetime
import io
from decimal import Decimal
from unittest import mock

from django.test import TestCase

from bookings.models import Appointment, AppointmentNote
from checkout.models import Sale, SaleItem
from clients.models import Client, ClientNote
from clients.summary import client_visit_summary
from clients.summary_export import (
    SUMMARY_FIELDNAMES,
    export_client_summaries,
    export_client_summaries_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset, hour=9):
    return NOW + datetime.timedelta(days=day_offset, hours=hour - 12)


class ClientSummaryExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Example Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(
            name="Other Salon", timezone="UTC"
        )
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One"
        )
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Haircut", service_minutes=45
        )

    def _client(self, first, last, salon=None):
        return Client.objects.create(
            salon=salon or self.salon, first_name=first, last_name=last,
            email="hidden@example.com", phone="555-0100",
        )

    def _appt(self, client, start, **kw):
        kw.setdefault("status", Appointment.Status.COMPLETED)
        return Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            start=start, end=start + datetime.timedelta(minutes=45), **kw,
        )

    def _sale(self, client, items=(), status=Sale.Status.COMPLETED):
        sale = Sale.objects.create(
            salon=self.salon, client=client, status=status
        )
        for price, qty in items:
            SaleItem.objects.create(
                sale=sale, kind=SaleItem.Kind.SERVICE,
                unit_price=Decimal(price), quantity=qty,
            )
        return sale

    def _parsed(self, *args, **kw):
        text = export_client_summaries_csv(*args, **kw)
        return list(csv.DictReader(io.StringIO(text)))

    def test_header_only_when_salon_has_no_clients(self):
        self._client("Olga", "Other", salon=self.other_salon)
        self.assertEqual(export_client_summaries(self.salon, now=NOW), [])
        self.assertEqual(
            export_client_summaries_csv(self.salon, now=NOW),
            ",".join(SUMMARY_FIELDNAMES) + "\n",
        )
        rows = list(csv.reader(io.StringIO(
            export_client_summaries_csv(self.salon, now=NOW))))
        self.assertEqual(rows, [SUMMARY_FIELDNAMES])

    def test_row_values_match_summary_service(self):
        client = self._client("Dana", "Due")
        past = self._appt(client, at(-10))
        self._appt(client, at(-1))
        self._appt(client, at(-2), status=Appointment.Status.CANCELLED)
        future = self._appt(
            client, at(3), status=Appointment.Status.BOOKED)
        self._sale(client, items=[("85.00", 1), ("20.00", 2)])
        self._sale(client, items=[("999.00", 1)], status=Sale.Status.VOIDED)
        ClientNote.objects.create(client=client, body="Record secret")
        AppointmentNote.objects.create(
            appointment=past, body="Appointment secret")
        self.assertEqual(
            SUMMARY_FIELDNAMES,
            ["client_id", "first_name", "last_name", "total_visits",
             "last_visit", "next_appointment_start", "lifetime_spend",
             "record_note_count", "appointment_note_count"],
        )
        summary = client_visit_summary(client, now=NOW)
        records = export_client_summaries(self.salon, now=NOW)
        self.assertEqual(records, [{
            "client_id": summary.client_id,
            "first_name": summary.client.first_name,
            "last_name": summary.client.last_name,
            "total_visits": summary.total_visits,
            "last_visit": summary.last_visit.isoformat(),
            "next_appointment_start": (
                summary.next_appointment_start.isoformat()),
            "lifetime_spend": str(summary.lifetime_spend),
            "record_note_count": summary.record_note_count,
            "appointment_note_count": summary.appointment_note_count,
        }])
        self.assertEqual(records[0]["total_visits"], 3)
        self.assertEqual(records[0]["lifetime_spend"], "125.00")
        self.assertEqual(records[0]["last_visit"], at(-1).isoformat())
        self.assertEqual(
            records[0]["next_appointment_start"], future.start.isoformat())
        parsed = self._parsed(self.salon, now=NOW)
        self.assertEqual(parsed, [{
            "client_id": str(client.pk), "first_name": "Dana",
            "last_name": "Due", "total_visits": "3",
            "last_visit": at(-1).isoformat(),
            "next_appointment_start": future.start.isoformat(),
            "lifetime_spend": "125.00", "record_note_count": "1",
            "appointment_note_count": "1",
        }])

    def test_delegates_to_summary_service_per_client(self):
        one = self._client("Ann", "Able")
        two = self._client("Bob", "Baker")
        with mock.patch(
            "clients.summary_export.client_visit_summary",
            wraps=client_visit_summary,
        ) as spy:
            records = export_client_summaries(self.salon, now=NOW)
        self.assertEqual(
            [call.args[0] for call in spy.call_args_list], [one, two])
        self.assertTrue(
            all(call.kwargs == {"now": NOW} for call in spy.call_args_list))
        self.assertEqual(
            [r["client_id"] for r in records], [one.pk, two.pk])

    def test_empty_history_client_has_zeroes_and_empty_fields(self):
        client = self._client("Nina", "Never")
        records = export_client_summaries(self.salon, now=NOW)
        self.assertEqual(records, [{
            "client_id": client.pk, "first_name": "Nina",
            "last_name": "Never", "total_visits": 0, "last_visit": None,
            "next_appointment_start": None, "lifetime_spend": "0.00",
            "record_note_count": 0, "appointment_note_count": 0,
        }])
        parsed = self._parsed(self.salon, now=NOW)
        self.assertEqual(parsed[0]["last_visit"], "")
        self.assertEqual(parsed[0]["next_appointment_start"], "")

    def test_ordering_by_last_first_then_id(self):
        zed = self._client("Zed", "Young")
        ann_y = self._client("Ann", "Young")
        ann_a = self._client("Ann", "Able")
        bob_a = self._client("Bob", "Able")
        ann_a2 = self._client("Ann", "Able")
        records = export_client_summaries(self.salon, now=NOW)
        self.assertEqual(
            [r["client_id"] for r in records],
            [ann_a.pk, ann_a2.pk, bob_a.pk, ann_y.pk, zed.pk],
        )
        parsed = self._parsed(self.salon, now=NOW)
        self.assertEqual(
            [r["client_id"] for r in parsed],
            [str(c) for c in
             [ann_a.pk, ann_a2.pk, bob_a.pk, ann_y.pk, zed.pk]],
        )

    def test_salon_scoping(self):
        mine = self._client("Mina", "Mine")
        theirs = self._client("Theo", "Theirs", salon=self.other_salon)
        self._appt(mine, at(-1))
        self._appt(theirs, at(-1))
        self._sale(theirs, items=[("70.00", 1)])
        records = export_client_summaries(self.salon, now=NOW)
        self.assertEqual([r["client_id"] for r in records], [mine.pk])
        self.assertNotIn(
            "Theirs", export_client_summaries_csv(self.salon, now=NOW))
        other = export_client_summaries(self.other_salon, now=NOW)
        self.assertEqual([r["client_id"] for r in other], [theirs.pk])
        self.assertEqual(other[0]["lifetime_spend"], "70.00")

    def test_no_contact_details_or_note_bodies_appear(self):
        client = self._client("Dana", "Due")
        appt = self._appt(client, at(-1))
        ClientNote.objects.create(client=client, body="Record secret")
        ClientNote.objects.create(client=client, body="Record two")
        AppointmentNote.objects.create(
            appointment=appt, body="Appointment secret")
        csv_text = export_client_summaries_csv(self.salon, now=NOW)
        for forbidden in (
            "hidden@example.com", "555-0100", "Record secret",
            "Record two", "Appointment secret",
        ):
            self.assertNotIn(forbidden, csv_text)
        record = export_client_summaries(self.salon, now=NOW)[0]
        self.assertEqual(record["record_note_count"], 2)
        self.assertEqual(record["appointment_note_count"], 1)
        self.assertNotIn("email", SUMMARY_FIELDNAMES)
        self.assertNotIn("phone", SUMMARY_FIELDNAMES)

    def test_read_only(self):
        client = self._client("Dana", "Due")
        self._appt(client, at(-1))
        before = (
            Client.objects.count(), Appointment.objects.count(),
            Sale.objects.count(), ClientNote.objects.count(),
            AppointmentNote.objects.count(),
        )
        export_client_summaries(self.salon, now=NOW)
        export_client_summaries_csv(self.salon, now=NOW)
        after = (
            Client.objects.count(), Appointment.objects.count(),
            Sale.objects.count(), ClientNote.objects.count(),
            AppointmentNote.objects.count(),
        )
        self.assertEqual(before, after)
