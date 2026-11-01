"""Tests for import_salon_data (Exit Test part 2: the restore side).

Synthetic in-test records only — no real salon/client data. The
centrepiece is a round trip: build records, export them with
export_salon_data, wipe the database, import, and assert the
restored records match on counts and key fields.
"""
import io
import json
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment, AppointmentNote
from clients.models import Client, ClientNote
from saloncore.models import (
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import StaffMember

MODELS = (Salon, ServiceCategory, Service, StaffLevel, ServicePrice,
          Client, ClientNote, StaffMember)


def _counts():
    return {m.__name__: m.objects.count() for m in MODELS}


class ImportSalonDataTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Restore Salon", timezone="America/New_York", currency="USD")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=1)
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-1", description="Root color",
            service_minutes=45, processing_minutes=30, finishing_minutes=15)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6", sort_order=6)
        self.price = ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"), is_from=True)
        self.client = Client.objects.create(
            salon=self.salon, external_id="cli-1", first_name="Ada",
            last_name="Optin", email="ada@example.com", phone="555-0100",
            sms_opt_in=True, email_opt_in=True)
        self.plain = Client.objects.create(
            salon=self.salon, first_name="Bob", last_name="Optout")
        self.note = ClientNote.objects.create(
            client=self.client, body="Prefers quiet appointments.",
            author_name="Front Desk")
        self.staff = StaffMember.objects.create(
            salon=self.salon, external_id="staff-1",
            display_name="Stylist One", staff_level=self.level,
            online_bookable=False)

    def temp_path(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        return fh.name

    def export(self):
        path = self.temp_path()
        call_command("export_salon_data", path, stdout=io.StringIO())
        return path

    def run_import(self, path):
        out = io.StringIO()
        call_command("import_salon_data", path, stdout=out)
        return out.getvalue()

    def test_round_trip_restores_counts_and_key_fields(self):
        before = _counts()
        path = self.export()
        Salon.objects.all().delete()
        self.assertTrue(all(c == 0 for c in _counts().values()))

        out = self.run_import(path)
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertEqual(_counts(), before)

        salon = Salon.objects.get()
        self.assertEqual(salon.name, "Restore Salon")
        self.assertEqual(salon.timezone, "America/New_York")
        service = Service.objects.get()
        self.assertEqual(service.external_id, "svc-1")
        self.assertEqual(service.name, "Single Process")
        self.assertEqual(service.service_minutes, 45)
        self.assertEqual(service.category.name, "Color")
        self.assertEqual(service.category.salon, salon)
        price = ServicePrice.objects.get()
        self.assertEqual(price.amount, Decimal("85.00"))
        self.assertTrue(price.is_from)
        self.assertEqual(price.service, service)
        self.assertEqual(price.staff_level.name, "Level 6")
        client = Client.objects.get(external_id="cli-1")
        self.assertEqual(client.email, "ada@example.com")
        self.assertTrue(client.sms_opt_in)
        self.assertTrue(client.email_opt_in)
        self.assertEqual(
            Client.objects.filter(first_name="Bob").count(), 1)
        note = ClientNote.objects.get()
        self.assertEqual(note.body, "Prefers quiet appointments.")
        self.assertEqual(note.author_name, "Front Desk")
        self.assertEqual(note.client, client)
        staff = StaffMember.objects.get()
        self.assertEqual(staff.external_id, "staff-1")
        self.assertEqual(staff.display_name, "Stylist One")
        self.assertFalse(staff.online_bookable)
        self.assertEqual(staff.staff_level.name, "Level 6")

    def test_reimport_is_idempotent(self):
        path = self.export()
        Salon.objects.all().delete()
        self.run_import(path)
        after_first = _counts()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(_counts(), after_first)

    def test_reimport_updates_in_place(self):
        path = self.export()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["service_prices"][0]["amount"] = "90.00"
        data["clients"][0]["phone"] = "555-0199"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        self.run_import(path)
        self.assertEqual(ServicePrice.objects.count(), 1)
        self.assertEqual(
            ServicePrice.objects.get().amount, Decimal("90.00"))
        self.assertEqual(Client.objects.count(), 2)
        self.assertEqual(
            Client.objects.get(external_id="cli-1").phone, "555-0199")

    def test_missing_file_raises(self):
        with self.assertRaises(CommandError):
            call_command("import_salon_data", "/nonexistent/nope.json")

    def test_invalid_json_raises_and_changes_nothing(self):
        path = self.temp_path()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        before = _counts()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(_counts(), before)

    def test_missing_section_raises(self):
        path = self.temp_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"salons": []}, fh)
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)

    def test_dangling_reference_raises_and_changes_nothing(self):
        path = self.export()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["services"][0]["category_id"] = 999999
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        # Validate-before-write: not even the salons were restored.
        self.assertTrue(all(c == 0 for c in _counts().values()))

    def load_export_data(self):
        path = self.export()
        with open(path, encoding="utf-8") as fh:
            return path, json.load(fh)

    def write_data(self, path, data):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_explicit_boolean_values_restore_exactly(self):
        # TF-3: explicit False stays False and explicit True stays
        # True — nothing is re-guessed from a default on restore.
        path, data = self.load_export_data()
        data["services"][0]["active"] = False
        data["service_categories"][0]["active"] = False
        data["staff_levels"][0]["active"] = False
        data["service_prices"][0]["is_from"] = False
        data["service_prices"][0]["active"] = False
        data["clients"][0]["active"] = False
        data["staff_members"][0]["online_bookable"] = True
        data["staff_members"][0]["active"] = False
        self.write_data(path, data)
        Salon.objects.all().delete()
        self.run_import(path)
        self.assertFalse(Service.objects.get().active)
        self.assertFalse(ServiceCategory.objects.get().active)
        self.assertFalse(StaffLevel.objects.get().active)
        price = ServicePrice.objects.get()
        self.assertFalse(price.is_from)
        self.assertFalse(price.active)
        self.assertFalse(Client.objects.get(external_id="cli-1").active)
        staff = StaffMember.objects.get()
        self.assertTrue(staff.online_bookable)
        self.assertFalse(staff.active)

    def test_bad_boolean_rejected_in_validation_with_zero_writes(self):
        # TF-3: string "false" must never become True, explicit null
        # is not a boolean, and 1 is not a boolean either. Every bad
        # shape is a phase-1 CommandError, so zero rows are written.
        cases = [
            ("services", "active", "false"),
            ("services", "active", None),
            ("service_categories", "active", "false"),
            ("service_categories", "active", None),
            ("staff_levels", "active", "false"),
            ("staff_levels", "active", None),
            ("service_prices", "is_from", "false"),
            ("service_prices", "is_from", None),
            ("service_prices", "active", "true"),
            ("service_prices", "active", 1),
            ("clients", "active", "false"),
            ("clients", "active", None),
            ("staff_members", "online_bookable", "false"),
            ("staff_members", "online_bookable", None),
            ("staff_members", "active", "false"),
            ("staff_members", "active", None),
        ]
        path, data = self.load_export_data()
        for section, field, bad in cases:
            with self.subTest(section=section, field=field, bad=bad):
                original = data[section][0][field]
                data[section][0][field] = bad
                self.write_data(path, data)
                Salon.objects.all().delete()
                with self.assertRaises(CommandError) as ctx:
                    call_command("import_salon_data", path)
                self.assertIn(field, str(ctx.exception))
                self.assertIn(section, str(ctx.exception))
                self.assertTrue(
                    all(c == 0 for c in _counts().values()))
                data[section][0][field] = original

    def test_missing_boolean_rejected_not_guessed(self):
        # TF-3: a missing boolean key is distinct from an explicit
        # value — it is a named phase-1 error, never silently
        # replaced with a guessed default.
        cases = [
            ("services", "active"),
            ("service_prices", "is_from"),
            ("staff_members", "online_bookable"),
        ]
        path, data = self.load_export_data()
        for section, field in cases:
            with self.subTest(section=section, field=field):
                original = data[section][0].pop(field)
                self.write_data(path, data)
                Salon.objects.all().delete()
                with self.assertRaises(CommandError) as ctx:
                    call_command("import_salon_data", path)
                self.assertIn(field, str(ctx.exception))
                self.assertTrue(
                    all(c == 0 for c in _counts().values()))
                data[section][0][field] = original

    def test_naive_created_at_rejected_with_zero_writes(self):
        # TF-7: a naive created_at (no offset) must never be stored
        # as-if-UTC under USE_TZ. Phase-1 CommandError, zero writes,
        # for every section whose created_at is restored here.
        path, data = self.load_export_data()
        for section in ("salons", "clients", "client_notes"):
            with self.subTest(section=section):
                original = data[section][0]["created_at"]
                data[section][0]["created_at"] = "2026-01-01T10:00:00"
                self.write_data(path, data)
                Salon.objects.all().delete()
                with self.assertRaises(CommandError) as ctx:
                    call_command("import_salon_data", path)
                self.assertIn("created_at", str(ctx.exception))
                self.assertIn(section, str(ctx.exception))
                self.assertTrue(
                    all(c == 0 for c in _counts().values()))
                data[section][0]["created_at"] = original

    def test_unparseable_created_at_rejected_with_zero_writes(self):
        path, data = self.load_export_data()
        data["clients"][0]["created_at"] = "not-a-datetime"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError) as ctx:
            call_command("import_salon_data", path)
        self.assertIn("created_at", str(ctx.exception))
        self.assertTrue(all(c == 0 for c in _counts().values()))

    def test_aware_created_at_restored_exactly(self):
        path, data = self.load_export_data()
        data["salons"][0]["created_at"] = "2020-03-04T05:06:07+00:00"
        data["clients"][0]["created_at"] = "2021-06-07T08:09:10-04:00"
        self.write_data(path, data)
        Salon.objects.all().delete()
        self.run_import(path)
        self.assertEqual(
            Salon.objects.get().created_at,
            datetime(2020, 3, 4, 5, 6, 7, tzinfo=dt_timezone.utc))
        self.assertEqual(
            Client.objects.get(external_id="cli-1").created_at,
            datetime(2021, 6, 7, 8, 9, 10,
                     tzinfo=dt_timezone(timedelta(hours=-4))))

    def test_absent_created_at_still_imports(self):
        # Absent is distinct from naive: nothing to restore, no error.
        path, data = self.load_export_data()
        for section in ("salons", "clients", "client_notes"):
            data[section][0].pop("created_at", None)
        self.write_data(path, data)
        before = _counts()
        Salon.objects.all().delete()
        self.run_import(path)
        self.assertEqual(_counts(), before)

    def test_dangling_reference_in_late_section_writes_nothing(self):
        # staff_members is the LAST section written; every earlier
        # section is valid. Pre-validation must still write zero rows.
        path = self.export()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["staff_members"][0]["staff_level_id"] = 999999
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertTrue(all(c == 0 for c in _counts().values()))


class ImportAppointmentsTests(TestCase):
    """EXP-APPT-b: appointments + appointment notes restore."""

    def setUp(self):
        self.salon = Salon.objects.create(
            name="Appt Restore Salon", timezone="America/New_York")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-1", service_minutes=45)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6")
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"))
        self.client = Client.objects.create(
            salon=self.salon, external_id="cli-1",
            first_name="Ada", last_name="Optin")
        self.staff = StaffMember.objects.create(
            salon=self.salon, external_id="staff-1",
            display_name="Stylist One", staff_level=self.level)
        self.start = datetime(2026, 11, 2, 14, 0,
                              tzinfo=dt_timezone.utc)
        self.appt = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, external_id="appt-1",
            start=self.start, end=self.start + timedelta(minutes=45),
            status=Appointment.Status.CONFIRMED,
            origin=Appointment.Origin.PHONE,
            price_override=Decimal("80.00"))
        self.orphan = Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=None,
            service_name="Off-book Service",
            start=self.start + timedelta(days=1),
            end=self.start + timedelta(days=1, minutes=30))
        AppointmentNote.objects.create(
            appointment=self.appt, body="Allergic to ammonia.",
            author_name="Front Desk")
        AppointmentNote.objects.create(
            appointment=self.appt, body="Arrives early.")

    def temp_path(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        return fh.name

    def load(self):
        path = self.temp_path()
        call_command("export_salon_data", path, stdout=io.StringIO())
        with open(path, encoding="utf-8") as fh:
            return path, json.load(fh)

    def write(self, path, data):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def run_import(self, path):
        out = io.StringIO()
        call_command("import_salon_data", path, stdout=out)
        return out.getvalue()

    def test_round_trip_appointments_and_notes(self):
        path, _ = self.load()
        Salon.objects.all().delete()
        self.assertEqual(Appointment.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("appointments=2", out)
        self.assertIn("appointment_notes=2", out)
        self.assertEqual(Appointment.objects.count(), 2)
        self.assertEqual(AppointmentNote.objects.count(), 2)
        appt = Appointment.objects.get(external_id="appt-1")
        self.assertEqual(appt.client.external_id, "cli-1")
        self.assertEqual(appt.staff_member.external_id, "staff-1")
        self.assertEqual(appt.service.external_id, "svc-1")
        self.assertEqual(appt.start, self.start)
        self.assertEqual(appt.end, self.start + timedelta(minutes=45))
        self.assertEqual(appt.status, "confirmed")
        self.assertEqual(appt.origin, "phone")
        self.assertEqual(appt.price_override, Decimal("80.00"))
        orphan = Appointment.objects.get(service_name="Off-book Service")
        self.assertIsNone(orphan.service)
        self.assertIsNone(orphan.price_override)
        bodies = set(appt.notes.values_list("body", flat=True))
        self.assertEqual(bodies, {"Allergic to ammonia.", "Arrives early."})
        note = appt.notes.get(body="Allergic to ammonia.")
        self.assertEqual(note.author_name, "Front Desk")

    def test_reimport_appointments_is_idempotent(self):
        path, _ = self.load()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(Appointment.objects.count(), 2)
        self.assertEqual(AppointmentNote.objects.count(), 2)

    def test_links_resolve_by_external_id_when_id_corrupt(self):
        path, data = self.load()
        for row in data["appointments"]:
            row["client_id"] = 999999
            row["staff_member_id"] = 999999
            row["service_id"] = 999999 if row["service_id"] else None
        self.write(path, data)
        Salon.objects.all().delete()
        self.run_import(path)
        appt = Appointment.objects.get(external_id="appt-1")
        self.assertEqual(appt.client.external_id, "cli-1")
        self.assertEqual(appt.service.external_id, "svc-1")

    def test_links_fall_back_to_file_id_when_external_unknown(self):
        path, data = self.load()
        for row in data["appointments"]:
            row["client_external_id"] = "no-such-client"
            row["staff_member_external_id"] = "no-such-staff"
            row["service_external_id"] = (
                "no-such-service" if row["service_id"] else None)
        self.write(path, data)
        Salon.objects.all().delete()
        self.run_import(path)
        self.assertEqual(Appointment.objects.count(), 2)

    def test_unknown_client_reference_fails_closed_no_writes(self):
        path, data = self.load()
        data["appointments"][0]["client_id"] = 999999
        data["appointments"][0]["client_external_id"] = "no-such"
        self.write(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError) as ctx:
            call_command("import_salon_data", path)
        self.assertIn("client", str(ctx.exception))
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_unknown_service_reference_fails_closed(self):
        path, data = self.load()
        data["appointments"][0]["service_id"] = 999999
        data["appointments"][0]["service_external_id"] = "no-such"
        self.write(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Appointment.objects.count(), 0)

    def test_naive_appointment_datetimes_rejected_no_writes(self):
        # TF-7 sibling paths: appointment created_at, note
        # created_at, and appointment start/end are all datetimes
        # restored by this command — naive values fail closed.
        cases = [
            ("appointments", "created_at"),
            ("appointment_notes", "created_at"),
            ("appointments", "start"),
            ("appointments", "end"),
        ]
        path, data = self.load()
        for section, field in cases:
            with self.subTest(section=section, field=field):
                original = data[section][0][field]
                data[section][0][field] = "2026-11-02T14:00:00"
                self.write(path, data)
                Salon.objects.all().delete()
                with self.assertRaises(CommandError) as ctx:
                    call_command("import_salon_data", path)
                self.assertIn(field, str(ctx.exception))
                self.assertEqual(Salon.objects.count(), 0)
                self.assertEqual(Appointment.objects.count(), 0)
                data[section][0][field] = original

    def test_unknown_note_appointment_ref_fails_closed(self):
        path, data = self.load()
        data["appointment_notes"][0]["appointment_id"] = 999999
        self.write(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError) as ctx:
            call_command("import_salon_data", path)
        self.assertIn("appointment", str(ctx.exception))
        self.assertEqual(Appointment.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 0)
