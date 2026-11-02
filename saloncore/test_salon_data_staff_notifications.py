"""StaffNotification leg: salon_data export/import keeps the inbox.

Synthetic records only. The stylist arrival inbox
(team.StaffNotification, PR #483) was the one model with no
salon_data section: a round trip silently lost every ping,
seen and unseen alike.
"""
import datetime
import hashlib
import io
import json
import tempfile

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from bookings.models import Appointment
from clients.models import Client
from saloncore.models import Salon, Service, ServiceCategory
from team.models import StaffMember, StaffNotification

UTC = datetime.timezone.utc
T1 = datetime.datetime(2026, 1, 1, 15, 0, tzinfo=UTC)
T1_SEEN = datetime.datetime(2026, 1, 1, 15, 5, tzinfo=UTC)
T2 = datetime.datetime(2026, 1, 2, 15, 0, tzinfo=UTC)
T3 = datetime.datetime(2026, 1, 1, 16, 0, tzinfo=UTC)


def _inbox():
    """The restored inbox as a set of natural keys + seen state."""
    return {
        (n.staff_member.external_id or n.staff_member.display_name,
         n.appointment.external_id or str(n.appointment.start),
         n.kind, n.created_at.isoformat(),
         n.seen_at.isoformat() if n.seen_at else None)
        for n in StaffNotification.objects.select_related(
            "staff_member", "appointment")
    }


def _digest(inbox):
    return hashlib.sha256(
        json.dumps(sorted(inbox, key=repr), sort_keys=True).encode()
    ).hexdigest()


def _stamp(note, created_at, seen_at=None):
    StaffNotification.objects.filter(pk=note.pk).update(
        created_at=created_at, seen_at=seen_at)
    note.refresh_from_db()


class SalonDataStaffNotificationsTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(name="Inbox Salon")
        category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.service = Service.objects.create(
            category=category, name="Cut", external_id="svc-cut",
            service_minutes=45)
        self.client = Client.objects.create(
            salon=self.salon, first_name="Robin", last_name="Guest")
        self.alice = StaffMember.objects.create(
            salon=self.salon, display_name="Alice",
            external_id="staff-a")
        self.beth = StaffMember.objects.create(
            salon=self.salon, display_name="Beth",
            external_id="staff-b")
        start = timezone.make_aware(datetime.datetime(2026, 1, 1, 10, 0))
        self.appt1 = Appointment.objects.create(
            client=self.client, staff_member=self.alice,
            service=self.service, service_name="Cut",
            external_id="appt-1", start=start,
            end=start + datetime.timedelta(hours=1))
        self.appt2 = Appointment.objects.create(
            client=self.client, staff_member=self.beth,
            service=self.service, service_name="Cut",
            external_id="appt-2",
            start=start + datetime.timedelta(hours=2),
            end=start + datetime.timedelta(hours=3))
        _stamp(StaffNotification.objects.create(
            staff_member=self.alice, appointment=self.appt1), T1, T1_SEEN)
        _stamp(StaffNotification.objects.create(
            staff_member=self.alice, appointment=self.appt1), T2)
        _stamp(StaffNotification.objects.create(
            staff_member=self.beth, appointment=self.appt2), T3)

    def temp_path(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        return fh.name

    def export_data(self):
        path = self.temp_path()
        call_command("export_salon_data", path, stdout=io.StringIO())
        with open(path, encoding="utf-8") as fh:
            return path, json.load(fh)

    def write_data(self, path, data):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def run_import(self, path):
        out = io.StringIO()
        call_command("import_salon_data", path, stdout=out)
        return out.getvalue()

    def test_export_emits_staff_notifications_with_all_fields(self):
        _, data = self.export_data()
        self.assertEqual(data["counts"]["staff_notifications"], 3)
        self.assertEqual(len(data["staff_notifications"]), 3)
        by_key = {
            (r["staff_member_external_id"], r["appointment_external_id"],
             r["created_at"]): r for r in data["staff_notifications"]}
        row = by_key[("staff-a", "appt-1", T1.isoformat())]
        self.assertEqual(row["staff_member_id"], self.alice.id)
        self.assertEqual(row["appointment_id"], self.appt1.id)
        self.assertEqual(row["kind"], "arrived")
        self.assertEqual(row["seen_at"], T1_SEEN.isoformat())
        # An unseen ping exports seen_at as None, verbatim.
        self.assertIsNone(by_key[("staff-b", "appt-2", T3.isoformat())]
                          ["seen_at"])

    def test_salon_filter_scopes_notifications_via_staff_member(self):
        other = Salon.objects.create(name="Other Salon")
        cat = ServiceCategory.objects.create(salon=other, name="Nails")
        svc = Service.objects.create(
            category=cat, name="Manicure", service_minutes=30)
        client = Client.objects.create(
            salon=other, first_name="Pat", last_name="Guest")
        staff = StaffMember.objects.create(
            salon=other, display_name="Other Stylist")
        start = timezone.make_aware(datetime.datetime(2026, 1, 3, 10, 0))
        appt = Appointment.objects.create(
            client=client, staff_member=staff, service=svc,
            service_name="Manicure", start=start,
            end=start + datetime.timedelta(hours=1))
        StaffNotification.objects.create(
            staff_member=staff, appointment=appt)
        path = self.temp_path()
        call_command("export_salon_data", path, salon="Inbox Salon",
                     stdout=io.StringIO())
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["counts"]["staff_notifications"], 3)
        call_command("export_salon_data", path, salon="Other Salon",
                     stdout=io.StringIO())
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["counts"]["staff_notifications"], 1)

    def test_round_trip_preserves_inbox_count_and_set_hash(self):
        before = _inbox()
        before_digest = _digest(before)
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(StaffNotification.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("staff_notifications=3", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(StaffNotification.objects.count(), len(before))
        self.assertEqual(_inbox(), before)
        self.assertEqual(_digest(_inbox()), before_digest)
        # The seen ping survived as seen; the unseen as unseen.
        alice = StaffMember.objects.get(external_id="staff-a")
        seen = StaffNotification.objects.filter(
            staff_member=alice, seen_at__isnull=False)
        self.assertEqual(seen.count(), 1)
        self.assertEqual(seen.get().seen_at, T1_SEEN)

    def test_reimport_is_idempotent_and_updates_seen_at_in_place(self):
        path, data = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(StaffNotification.objects.count(), 3)
        row = next(r for r in data["staff_notifications"]
                   if r["created_at"] == T2.isoformat())
        later = datetime.datetime(2026, 1, 2, 15, 9, tzinfo=UTC)
        row["seen_at"] = later.isoformat()
        self.write_data(path, data)
        self.run_import(path)
        self.assertEqual(StaffNotification.objects.count(), 3)
        note = StaffNotification.objects.get(created_at=T2)
        self.assertEqual(note.seen_at, later)

    def test_links_resolve_by_external_id_not_raw_pk(self):
        path, data = self.export_data()
        for row in data["staff_notifications"]:
            row["staff_member_id"] = 999999
            row["appointment_id"] = 999999
        self.write_data(path, data)
        Salon.objects.all().delete()
        self.run_import(path)
        self.assertEqual(StaffNotification.objects.count(), 3)

    def test_missing_staff_notifications_section_imports_as_before(self):
        path, data = self.export_data()
        del data["staff_notifications"]
        del data["counts"]["staff_notifications"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("staff_notifications=0", out)
        self.assertEqual(StaffNotification.objects.count(), 0)
        self.assertEqual(StaffMember.objects.count(), 2)

    def test_dangling_appointment_ref_fails_closed_with_zero_writes(self):
        path, data = self.export_data()
        data["staff_notifications"][0]["appointment_id"] = 999999
        data["staff_notifications"][0]["appointment_external_id"] = (
            "appt-nope")
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(StaffNotification.objects.count(), 0)

    def test_naive_created_at_fails_closed_with_zero_writes(self):
        path, data = self.export_data()
        data["staff_notifications"][0]["created_at"] = (
            "2026-01-01T15:00:00")
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(StaffNotification.objects.count(), 0)

    def test_unknown_key_in_staff_notifications_named_not_dropped(self):
        path, data = self.export_data()
        data["staff_notifications"][0]["legacy_code"] = "X-1"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("staff_notifications.legacy_code", out)
        self.assertEqual(StaffNotification.objects.count(), 3)
