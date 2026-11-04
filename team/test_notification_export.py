"""Staff notification export: stored rows verbatim, salon-scoped."""
import csv
import datetime
import io

from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember, StaffNotification
from team.notification_export import (
    EXPORT_FIELDNAMES,
    NOTIFICATION_EXPORT_FIELDNAMES,
    export_staff_notifications,
    export_staff_notifications_csv,
    staff_notifications_csv,
)
from team.notifications import staff_notifications

UTC = datetime.timezone.utc
T1 = datetime.datetime(2026, 1, 1, 15, 0, tzinfo=UTC)
T1_SEEN = datetime.datetime(2026, 1, 1, 15, 5, tzinfo=UTC)
T2 = datetime.datetime(2026, 1, 2, 15, 0, tzinfo=UTC)


def _stamp(note, created_at, seen_at=None):
    StaffNotification.objects.filter(pk=note.pk).update(
        created_at=created_at, seen_at=seen_at)
    note.refresh_from_db()
    return note


class StaffNotificationExportTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Inbox Salon", timezone="UTC")
        self.other_salon = Salon.objects.create(name="Other", timezone="UTC")
        category = ServiceCategory.objects.create(salon=self.salon, name="Hair")
        self.service = Service.objects.create(
            category=category, name="Cut", service_minutes=60)
        # PIN and email are set so the hygiene test is meaningful.
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Dana",
            pin="1234", email="dana@example.com")
        self.other_staff = StaffMember.objects.create(
            salon=self.other_salon, display_name="Other Dana")
        client = Client.objects.create(
            salon=self.salon, first_name="Robin", last_name="Guest")
        start = timezone.now().replace(hour=10, minute=0, second=0,
                                       microsecond=0)
        self.appt = Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            service_name="Cut", start=start,
            end=start + datetime.timedelta(hours=1))
        self.appt2 = Appointment.objects.create(
            client=client, staff_member=self.staff, service=self.service,
            service_name="Cut", start=start + datetime.timedelta(days=1),
            end=start + datetime.timedelta(days=1, hours=1))

    def _note(self, appt=None, staff=None, kind="arrived",
              created=T1, seen=None):
        note = StaffNotification.objects.create(
            staff_member=staff or self.staff,
            appointment=appt or self.appt, kind=kind)
        return _stamp(note, created, seen)

    def test_header_and_dict_keys(self):
        self._note()
        text = export_staff_notifications_csv(self.salon)
        lines = list(csv.reader(io.StringIO(text)))
        self.assertEqual(lines[0], NOTIFICATION_EXPORT_FIELDNAMES)
        self.assertEqual(EXPORT_FIELDNAMES, NOTIFICATION_EXPORT_FIELDNAMES)
        records = export_staff_notifications(self.salon)
        self.assertEqual(len(records), 1)
        self.assertEqual(list(records[0].keys()),
                         NOTIFICATION_EXPORT_FIELDNAMES)
        self.assertIs(staff_notifications_csv,
                      export_staff_notifications_csv)

    def test_rows_are_stored_values_verbatim(self):
        seen_note = self._note(created=T1, seen=T1_SEEN)
        unseen = self._note(appt=self.appt2, kind="arrived", created=T2)
        records = export_staff_notifications(self.salon)
        # Newest first, exactly as stored -- no recomputation.
        self.assertEqual([r["id"] for r in records],
                         [unseen.pk, seen_note.pk])
        self.assertEqual(records[0], {
            "id": unseen.pk, "salon_id": self.salon.pk,
            "staff_member_id": self.staff.pk, "staff_name": "Dana",
            "appointment_id": self.appt2.pk, "kind": "arrived",
            "created_at": T2.isoformat(), "seen_at": None})
        self.assertEqual(records[1]["created_at"], T1.isoformat())
        self.assertEqual(records[1]["seen_at"], T1_SEEN.isoformat())
        # Service returns the same rows in the same order.
        self.assertEqual(
            [n.pk for n in staff_notifications(self.salon)],
            [unseen.pk, seen_note.pk])
        # CSV agrees with the dict export.
        parsed = list(csv.DictReader(io.StringIO(
            export_staff_notifications_csv(self.salon))))
        self.assertEqual(len(parsed), len(records))
        self.assertEqual(parsed[1]["seen_at"], T1_SEEN.isoformat())
        self.assertEqual(parsed[0]["seen_at"], "")

    def test_salon_scoping_and_empty(self):
        self._note()
        self._note(staff=self.other_staff)
        self.assertEqual(len(export_staff_notifications(self.salon)), 1)
        empty = Salon.objects.create(name="Empty", timezone="UTC")
        self.assertEqual(export_staff_notifications(empty), [])
        self.assertEqual(
            export_staff_notifications_csv(empty),
            ",".join(NOTIFICATION_EXPORT_FIELDNAMES) + "\n")

    def test_no_pin_or_email_anywhere(self):
        self._note()
        self.assertNotIn("pin", NOTIFICATION_EXPORT_FIELDNAMES)
        self.assertNotIn("email", NOTIFICATION_EXPORT_FIELDNAMES)
        text = export_staff_notifications_csv(self.salon)
        self.assertNotIn("1234", text)
        self.assertNotIn("dana@example.com", text)
        for record in export_staff_notifications(self.salon):
            self.assertNotIn("1234", [str(v) for v in record.values()])
            self.assertNotIn("dana@example.com",
                             [str(v) for v in record.values()])

    def test_default_none_is_salon_wide_unchanged(self):
        self._note()
        self._note(appt=self.appt2, created=T2)
        expected_records = export_staff_notifications(self.salon)
        expected_csv = export_staff_notifications_csv(self.salon)
        self.assertEqual(
            export_staff_notifications(self.salon, staff_member=None),
            expected_records)
        self.assertEqual(
            export_staff_notifications_csv(
                self.salon, staff_member=None),
            expected_csv)

    def test_filtered_by_staff_member(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        mine = self._note()
        self._note(staff=eve, appt=self.appt2, created=T2)
        records = export_staff_notifications(
            self.salon, staff_member=self.staff)
        self.assertEqual([r["id"] for r in records], [mine.pk])
        self.assertTrue(
            all(r["staff_name"] == "Dana" for r in records))
        parsed = list(csv.DictReader(io.StringIO(
            export_staff_notifications_csv(
                self.salon, staff_member=self.staff))))
        self.assertEqual([int(r["id"]) for r in parsed], [mine.pk])

    def test_filtered_staff_member_with_no_notifications(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        self._note()
        self.assertEqual(
            export_staff_notifications(self.salon, staff_member=eve),
            [])
        self.assertEqual(
            export_staff_notifications_csv(
                self.salon, staff_member=eve),
            ",".join(NOTIFICATION_EXPORT_FIELDNAMES) + "\n")

    def test_filtered_other_salon_staff_member_is_empty(self):
        self._note()
        self._note(staff=self.other_staff)
        self.assertEqual(
            export_staff_notifications(
                self.salon, staff_member=self.other_staff),
            [])

    def test_default_kind_none_is_unchanged(self):
        self._note()
        self._note(appt=self.appt2, kind="reminder", created=T2)
        expected_records = export_staff_notifications(self.salon)
        expected_csv = export_staff_notifications_csv(self.salon)
        self.assertEqual(
            export_staff_notifications(self.salon, kind=None),
            expected_records)
        self.assertEqual(
            export_staff_notifications_csv(self.salon, kind=None),
            expected_csv)

    def test_filtered_by_kind_exact_match(self):
        arrived = self._note(kind="arrived")
        self._note(appt=self.appt2, kind="reminder", created=T2)
        records = export_staff_notifications(
            self.salon, kind="arrived")
        self.assertEqual([r["id"] for r in records], [arrived.pk])
        self.assertTrue(all(r["kind"] == "arrived" for r in records))
        parsed = list(csv.DictReader(io.StringIO(
            export_staff_notifications_csv(self.salon, kind="arrived"))))
        self.assertEqual([int(r["id"]) for r in parsed], [arrived.pk])
        # Exact stored-value matching: no substring or case folding.
        self.assertEqual(
            export_staff_notifications(self.salon, kind="arriv"), [])
        self.assertEqual(
            export_staff_notifications(self.salon, kind="Arrived"), [])
        self.assertEqual(
            export_staff_notifications(self.salon, kind="unknown"), [])
        self.assertEqual(
            export_staff_notifications_csv(self.salon, kind="unknown"),
            ",".join(NOTIFICATION_EXPORT_FIELDNAMES) + "\n")

    def test_kind_composes_with_staff_member(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        mine = self._note(kind="arrived")
        self._note(kind="reminder", created=T2)
        self._note(staff=eve, appt=self.appt2, kind="arrived",
                   created=T2)
        records = export_staff_notifications(
            self.salon, staff_member=self.staff, kind="arrived")
        self.assertEqual([r["id"] for r in records], [mine.pk])
        parsed = list(csv.DictReader(io.StringIO(
            export_staff_notifications_csv(
                self.salon, staff_member=self.staff, kind="arrived"))))
        self.assertEqual([int(r["id"]) for r in parsed], [mine.pk])
        self.assertEqual(
            export_staff_notifications(
                self.salon, staff_member=eve, kind="reminder"),
            [])

    def test_default_seen_none_is_unchanged(self):
        self._note(seen=T1_SEEN)
        self._note(appt=self.appt2, created=T2)
        expected_records = export_staff_notifications(self.salon)
        expected_csv = export_staff_notifications_csv(self.salon)
        self.assertEqual(
            export_staff_notifications(self.salon, seen=None),
            expected_records)
        self.assertEqual(
            export_staff_notifications_csv(self.salon, seen=None),
            expected_csv)

    def test_filtered_by_seen(self):
        seen_note = self._note(seen=T1_SEEN)
        self._note(appt=self.appt2, created=T2)
        records = export_staff_notifications(self.salon, seen=True)
        self.assertEqual([r["id"] for r in records], [seen_note.pk])
        self.assertIsNotNone(records[0]["seen_at"])
        parsed = list(csv.DictReader(io.StringIO(
            export_staff_notifications_csv(self.salon, seen=True))))
        self.assertEqual([int(r["id"]) for r in parsed], [seen_note.pk])

    def test_filtered_by_unseen(self):
        self._note(seen=T1_SEEN)
        unseen = self._note(appt=self.appt2, created=T2)
        records = export_staff_notifications(self.salon, seen=False)
        self.assertEqual([r["id"] for r in records], [unseen.pk])
        self.assertIsNone(records[0]["seen_at"])
        parsed = list(csv.DictReader(io.StringIO(
            export_staff_notifications_csv(self.salon, seen=False))))
        self.assertEqual([int(r["id"]) for r in parsed], [unseen.pk])
        empty = Salon.objects.create(name="NoSeen", timezone="UTC")
        self.assertEqual(
            export_staff_notifications_csv(empty, seen=True),
            ",".join(NOTIFICATION_EXPORT_FIELDNAMES) + "\n")

    def test_seen_composes_with_staff_member_and_kind(self):
        eve = StaffMember.objects.create(
            salon=self.salon, display_name="Eve")
        mine = self._note(kind="arrived", seen=T1_SEEN)
        self._note(kind="reminder", created=T2, seen=T1_SEEN)
        unseen_mine = self._note(kind="arrived", created=T2)
        self._note(staff=eve, appt=self.appt2, kind="arrived",
                   created=T2, seen=T1_SEEN)
        records = export_staff_notifications(
            self.salon, staff_member=self.staff, kind="arrived",
            seen=True)
        self.assertEqual([r["id"] for r in records], [mine.pk])
        parsed = list(csv.DictReader(io.StringIO(
            export_staff_notifications_csv(
                self.salon, staff_member=self.staff, kind="arrived",
                seen=True))))
        self.assertEqual([int(r["id"]) for r in parsed], [mine.pk])
        self.assertEqual(
            [r["id"] for r in export_staff_notifications(
                self.salon, staff_member=self.staff, kind="arrived",
                seen=False)],
            [unseen_mine.pk])

    def test_read_only(self):
        self._note()
        before = StaffNotification.objects.count()
        export_staff_notifications(self.salon)
        export_staff_notifications_csv(self.salon)
        list(staff_notifications(self.salon))
        self.assertEqual(StaffNotification.objects.count(), before)
