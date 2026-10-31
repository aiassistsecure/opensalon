import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from clients.models import Client
from clients.rebooking import rebooking_candidates
from clients.rebooking_export import (
    REBOOKING_FIELDNAMES,
    export_rebooking_candidates,
    export_rebooking_csv,
)
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
REF = datetime.date(2026, 11, 2)


def at(day_offset, hour=12):
    return datetime.datetime.combine(
        REF + datetime.timedelta(days=day_offset),
        datetime.time(hour, 0),
        tzinfo=UTC,
    )


class RebookingExportTests(TestCase):
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
            salon=salon or self.salon, first_name=first, last_name=last
        )

    def _appt(self, client, start, **kw):
        kw.setdefault("status", Appointment.Status.COMPLETED)
        return Appointment.objects.create(
            client=client,
            staff_member=self.staff,
            service=self.service,
            start=start,
            end=start + datetime.timedelta(minutes=45),
            **kw,
        )

    def _parsed(self, *args, **kw):
        return list(csv.DictReader(io.StringIO(export_rebooking_csv(*args, **kw))))

    def test_header_only_when_no_candidates(self):
        self._client("Nina", "Never")
        old = self._client("Olga", "Old")
        self._appt(old, at(-100))
        self.assertEqual(
            export_rebooking_candidates(self.salon, reference_date=REF), []
        )
        self.assertEqual(
            export_rebooking_csv(self.salon, reference_date=REF),
            ",".join(REBOOKING_FIELDNAMES) + "\n",
        )
        rows = list(csv.reader(io.StringIO(
            export_rebooking_csv(self.salon, reference_date=REF))))
        self.assertEqual(rows, [REBOOKING_FIELDNAMES])

    def test_header_and_row_values_match_service(self):
        due = self._client("Dana", "Due")
        appt = self._appt(due, at(-20))
        self.assertEqual(
            REBOOKING_FIELDNAMES,
            ["client_id", "first_name", "last_name",
             "last_visit_date", "days_since_last_visit"],
        )
        service_rows = rebooking_candidates(
            self.salon, reference_date=REF, lookback_days=42)
        records = export_rebooking_candidates(
            self.salon, reference_date=REF, lookback_days=42)
        self.assertEqual(len(records), len(service_rows))
        self.assertEqual(records, [{
            "client_id": service_rows[0].client_id,
            "first_name": service_rows[0].client.first_name,
            "last_name": service_rows[0].client.last_name,
            "last_visit_date": service_rows[0].last_visit_date.isoformat(),
            "days_since_last_visit": service_rows[0].days_since_last_visit,
        }])
        self.assertEqual(records[0], {
            "client_id": due.pk,
            "first_name": "Dana",
            "last_name": "Due",
            "last_visit_date": appt.start.date().isoformat(),
            "days_since_last_visit": 20,
        })
        parsed = self._parsed(self.salon, reference_date=REF)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0], {
            "client_id": str(due.pk),
            "first_name": "Dana",
            "last_name": "Due",
            "last_visit_date": appt.start.date().isoformat(),
            "days_since_last_visit": "20",
        })

    def test_ordering_and_exclusions_match_service(self):
        newest = self._client("Nora", "Newest")
        self._appt(newest, at(-5))
        oldest = self._client("Ola", "Oldest")
        self._appt(oldest, at(-40))
        booked = self._client("Bea", "Booked")
        self._appt(booked, at(-20))
        self._appt(booked, at(14), status=Appointment.Status.BOOKED)
        records = export_rebooking_candidates(self.salon, reference_date=REF)
        self.assertEqual(
            [r["client_id"] for r in records], [oldest.pk, newest.pk])
        csv_text = export_rebooking_csv(self.salon, reference_date=REF)
        self.assertNotIn("Booked", csv_text)

    def test_window_passthrough(self):
        client = self._client("Wendy", "Window")
        self._appt(client, at(-20))
        self.assertEqual(
            export_rebooking_candidates(
                self.salon, reference_date=REF, lookback_days=14), []
        )
        records = export_rebooking_candidates(
            self.salon, reference_date=REF, lookback_days=21)
        self.assertEqual([r["client_id"] for r in records], [client.pk])
        records = export_rebooking_candidates(
            self.salon, reference_date=REF, window_days=21)
        self.assertEqual([r["client_id"] for r in records], [client.pk])
        self.assertIn(
            "Window",
            export_rebooking_csv(self.salon, reference_date=REF, window_days=21),
        )

    def test_salon_scoping(self):
        mine = self._client("Mina", "Mine")
        theirs = self._client("Theo", "Theirs", salon=self.other_salon)
        self._appt(mine, at(-20))
        self._appt(theirs, at(-20))
        records = export_rebooking_candidates(self.salon, reference_date=REF)
        self.assertEqual([r["client_id"] for r in records], [mine.pk])
        self.assertNotIn(
            "Theirs", export_rebooking_csv(self.salon, reference_date=REF))
        other = export_rebooking_candidates(self.other_salon, reference_date=REF)
        self.assertEqual([r["client_id"] for r in other], [theirs.pk])

    def test_read_only(self):
        client = self._client("Dana", "Due")
        self._appt(client, at(-20))
        before = (Client.objects.count(), Appointment.objects.count())
        export_rebooking_candidates(self.salon, reference_date=REF)
        export_rebooking_csv(self.salon, reference_date=REF)
        self.assertEqual(
            (Client.objects.count(), Appointment.objects.count()), before)
