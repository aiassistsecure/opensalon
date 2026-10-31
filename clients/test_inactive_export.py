import csv
import datetime
import io

from django.test import TestCase

from bookings.models import Appointment
from clients.inactive_export import (
    INACTIVE_FIELDNAMES,
    export_inactive_clients,
    export_inactive_csv,
)
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember

UTC = datetime.timezone.utc
NOW = datetime.datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def at(day_offset):
    return NOW + datetime.timedelta(days=day_offset)


class InactiveExportTests(TestCase):
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
        return Appointment.objects.create(
            client=client,
            staff_member=self.staff,
            service=self.service,
            start=start,
            end=start + datetime.timedelta(minutes=45),
            **kw,
        )

    def _parsed(self, *args, **kw):
        return list(csv.DictReader(io.StringIO(export_inactive_csv(*args, **kw))))

    def test_header_only_when_no_inactive_clients(self):
        recent = self._client("Rhea", "Recent")
        self._appt(recent, at(-1))
        self.assertEqual(
            export_inactive_clients(salon=self.salon, now=NOW), []
        )
        self.assertEqual(
            export_inactive_csv(salon=self.salon, now=NOW),
            ",".join(INACTIVE_FIELDNAMES) + "\n",
        )
        rows = list(csv.reader(io.StringIO(
            export_inactive_csv(salon=self.salon, now=NOW))))
        self.assertEqual(rows, [INACTIVE_FIELDNAMES])

    def test_header_and_row_for_stale_client(self):
        stale = self._client("Stella", "Stale")
        appt = self._appt(stale, at(-100))
        self.assertEqual(
            INACTIVE_FIELDNAMES,
            ["client_id", "first_name", "last_name",
             "last_appointment_date", "days_since_last_visit"],
        )
        records = export_inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(records, [{
            "client_id": stale.pk,
            "first_name": "Stella",
            "last_name": "Stale",
            "last_appointment_date": appt.start.date().isoformat(),
            "days_since_last_visit": 100,
        }])
        parsed = self._parsed(salon=self.salon, now=NOW)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0], {
            "client_id": str(stale.pk),
            "first_name": "Stella",
            "last_name": "Stale",
            "last_appointment_date": appt.start.date().isoformat(),
            "days_since_last_visit": "100",
        })

    def test_recently_active_client_excluded(self):
        recent = self._client("Rhea", "Recent")
        stale = self._client("Stella", "Stale")
        self._appt(recent, at(-5))
        self._appt(stale, at(-100))
        records = export_inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual([r["client_id"] for r in records], [stale.pk])
        self.assertNotIn("Recent", export_inactive_csv(salon=self.salon, now=NOW))

    def test_threshold_passthrough(self):
        client = self._client("Tessa", "Threshold")
        self._appt(client, at(-30))
        # Within a 60-day window: not inactive.
        self.assertEqual(
            export_inactive_clients(salon=self.salon, days=60, now=NOW), []
        )
        # With a 14-day threshold the same visit is stale.
        records = export_inactive_clients(salon=self.salon, days=14, now=NOW)
        self.assertEqual([r["client_id"] for r in records], [client.pk])
        self.assertEqual(records[0]["days_since_last_visit"], 30)
        # threshold_days alias is passed through too.
        records = export_inactive_clients(
            salon=self.salon, threshold_days=14, now=NOW)
        self.assertEqual([r["client_id"] for r in records], [client.pk])
        csv_text = export_inactive_csv(
            salon=self.salon, threshold_days=14, now=NOW)
        self.assertIn("Threshold", csv_text)

    def test_salon_scoping(self):
        mine = self._client("Mina", "Mine")
        theirs = self._client("Theo", "Theirs", salon=self.other_salon)
        self._appt(mine, at(-100))
        self._appt(theirs, at(-120))
        records = export_inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual([r["client_id"] for r in records], [mine.pk])
        self.assertNotIn("Theirs", export_inactive_csv(salon=self.salon, now=NOW))
        other = export_inactive_clients(salon=self.other_salon, now=NOW)
        self.assertEqual([r["client_id"] for r in other], [theirs.pk])

    def test_never_visited_client_has_empty_last_visit_fields(self):
        client = self._client("Nina", "Never")
        records = export_inactive_clients(salon=self.salon, now=NOW)
        self.assertEqual(records, [{
            "client_id": client.pk,
            "first_name": "Nina",
            "last_name": "Never",
            "last_appointment_date": None,
            "days_since_last_visit": None,
        }])
        parsed = self._parsed(salon=self.salon, now=NOW)
        self.assertEqual(parsed[0]["last_appointment_date"], "")
        self.assertEqual(parsed[0]["days_since_last_visit"], "")

    def test_read_only(self):
        client = self._client("Stella", "Stale")
        self._appt(client, at(-100))
        before = (Client.objects.count(), Appointment.objects.count())
        export_inactive_clients(salon=self.salon, now=NOW)
        export_inactive_csv(salon=self.salon, now=NOW)
        self.assertEqual(
            (Client.objects.count(), Appointment.objects.count()), before)
