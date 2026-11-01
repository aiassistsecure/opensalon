"""Tests for import_salon_data (Exit Test part 2: the restore side).

Synthetic in-test records only — no real salon/client data. The
centrepiece is a round trip: build records, export them with
export_salon_data, wipe the database, import, and assert the
restored records match on counts and key fields.
"""
import io
import json
import tempfile
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.core.management import CommandError, call_command
from django.test import TestCase

from bookings.models import Appointment, AppointmentNote, Break
from checkout.models import Cashup, Payment, Receipt, Refund, Sale, SaleItem
from catalog.models import Product, StockMovement
from clients.models import Client, ClientNote
from messaging.models import ReminderSend
from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from team.models import (
    AttendanceRecord,
    RosterPattern,
    ShiftOverride,
    StaffMember,
)

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

    def test_round_trip_restores_every_salon_self_field(self):
        # Cycle 72: every carried Salon self-field round-trips with
        # its full value — including currency, which the older
        # round-trip test never asserted. Distinctive values are
        # set first so a default could not masquerade as a restore.
        self.salon.timezone = "Europe/Paris"
        self.salon.currency = "EUR"
        self.salon.save()
        created_at = Salon.objects.get().created_at
        path = self.export()
        Salon.objects.all().delete()
        self.run_import(path)
        salon = Salon.objects.get()
        self.assertEqual(salon.name, "Restore Salon")
        self.assertEqual(salon.timezone, "Europe/Paris")
        self.assertEqual(salon.currency, "EUR")
        self.assertEqual(salon.created_at, created_at)

    def test_reimport_salon_updates_self_fields_in_place(self):
        # Idempotent re-import: changed self-fields update the SAME
        # salon row (keyed by name) — no duplicate salon is created.
        path = self.export()
        Salon.objects.all().delete()
        self.run_import(path)
        first_pk = Salon.objects.get().pk
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["salons"][0]["timezone"] = "America/Chicago"
        data["salons"][0]["currency"] = "CAD"
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        self.run_import(path)
        self.assertEqual(Salon.objects.count(), 1)
        salon = Salon.objects.get()
        self.assertEqual(salon.pk, first_pk)
        self.assertEqual(salon.timezone, "America/Chicago")
        self.assertEqual(salon.currency, "CAD")

    def test_salon_settings_section_is_named_as_dropped(self):
        # There is no SalonSettings model in any app, so a file
        # carrying a salon_settings section has no model home for
        # it: TF-11 must name it as dropped (never silently drop,
        # never invent fields to consume it), while the salons
        # section itself imports exactly as before.
        path = self.export()
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["salon_settings"] = [{"salon_id": data["salons"][0]["id"]}]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("IMPORT_DROPPED", out)
        self.assertIn("unknown_sections=salon_settings", out)
        self.assertEqual(Salon.objects.count(), 1)
        self.assertEqual(Salon.objects.get().timezone,
                         "America/New_York")

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

    def test_unknown_section_named_in_summary(self):
        # TF-11: an unknown top-level section is listed BY NAME in
        # the summary output, never dropped silently.
        path, data = self.load_export_data()
        data["mystery_section"] = [{"legacy_field": 1}]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("IMPORT_DROPPED", out)
        self.assertIn("unknown_sections=mystery_section", out)

    def test_unknown_keys_named_in_summary(self):
        # TF-11: unknown keys inside known section records are
        # listed BY NAME as section.key, across sections.
        path, data = self.load_export_data()
        data["clients"][0]["legacy_loyalty_code"] = "GOLD-9"
        data["services"][0]["legacy_vendor_flag"] = True
        data["salons"][0]["legacy_region"] = "north"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("clients.legacy_loyalty_code", out)
        self.assertIn("services.legacy_vendor_flag", out)
        self.assertIn("salons.legacy_region", out)

    def test_unknown_data_known_data_still_imports_identically(self):
        # TF-11: naming the drops must not change the restore —
        # counts and key fields match a clean round trip exactly.
        path, data = self.load_export_data()
        data["mystery_section"] = [{"x": 1}]
        data["clients"][0]["legacy_loyalty_code"] = "GOLD-9"
        self.write_data(path, data)
        before = _counts()
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertEqual(_counts(), before)
        self.assertEqual(Service.objects.get().external_id, "svc-1")
        self.assertEqual(
            Client.objects.get(external_id="cli-1").email,
            "ada@example.com")
        self.assertIn("mystery_section", out)
        self.assertIn("clients.legacy_loyalty_code", out)

    def test_zero_silent_drops(self):
        # TF-11: a clean file explicitly reports no drops, and a
        # file carrying both kinds of unknown data names BOTH —
        # there is no path where a drop goes unlisted.
        path, data = self.load_export_data()
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn(
            "IMPORT_DROPPED unknown_sections=none unknown_keys=none",
            out)
        path, data = self.load_export_data()
        data["extra_top"] = []
        data["staff_members"][0]["legacy_badge_no"] = "B-1"
        data["counts"]["extra_top"] = 0
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        dropped = [ln for ln in out.splitlines()
                   if ln.startswith("IMPORT_DROPPED")]
        self.assertEqual(len(dropped), 1)
        self.assertIn("extra_top", dropped[0])
        self.assertIn("staff_members.legacy_badge_no", dropped[0])
        self.assertIn("counts.extra_top", dropped[0])
        self.assertNotIn("none", dropped[0])

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


LIMIT = 64  # external_id max_length on Service/Client/StaffMember/Appointment


def _minimal_data():
    """A small export-shaped salon_data file (synthetic ids only)."""
    return {
        "salons": [{"id": 1, "name": "TF6 Salon", "timezone": "UTC",
                    "currency": "USD"}],
        "service_categories": [
            {"id": 10, "salon_id": 1, "name": "Color", "sort_order": 1,
             "active": True}],
        "services": [
            {"id": 20, "category_id": 10, "external_id": "svc-1",
             "name": "Single Process", "description": "",
             "service_minutes": 45, "processing_minutes": 0,
             "finishing_minutes": 0, "active": True}],
        "staff_levels": [
            {"id": 30, "salon_id": 1, "name": "Level 6", "sort_order": 6,
             "active": True}],
        "service_prices": [
            {"id": 40, "service_id": 20, "staff_level_id": 30,
             "amount": "85.00", "is_from": True, "active": True}],
        "clients": [
            {"id": 50, "salon_id": 1, "external_id": "cli-1",
             "first_name": "Ada", "last_name": "Optin", "email": "",
             "phone": "", "sms_opt_in": False, "email_opt_in": False,
             "active": True}],
        "client_notes": [],
        "staff_members": [
            {"id": 60, "salon_id": 1, "external_id": "staff-1",
             "display_name": "Stylist One", "staff_level_id": 30,
             "online_bookable": True, "active": True}],
        "appointments": [
            {"id": 70, "external_id": "appt-1", "client_id": 50,
             "client_external_id": "cli-1", "staff_member_id": 60,
             "staff_member_external_id": "staff-1", "service_id": 20,
             "service_external_id": "svc-1", "service_name": "",
             "start": "2026-11-02T14:00:00+00:00",
             "end": "2026-11-02T14:45:00+00:00",
             "status": "booked", "origin": "phone",
             "price_override": None}],
        "appointment_notes": [],
    }


class ImportSalonDataExternalIdTests(TestCase):
    """TF-6: faithful external ids — no truncation, str-normalised."""

    def temp_path(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        return fh.name

    def run_data(self, data):
        path = self.temp_path()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        out = io.StringIO()
        call_command("import_salon_data", path, stdout=out)
        return out.getvalue()

    def assert_zero_written(self):
        for model in (Salon, ServiceCategory, Service, StaffLevel,
                      ServicePrice, Client, ClientNote, StaffMember,
                      Appointment, AppointmentNote):
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def test_overlong_external_id_fails_naming_row_zero_writes(self):
        cases = [
            ("clients", "external_id"),
            ("staff_members", "external_id"),
            ("services", "external_id"),
            ("appointments", "external_id"),
            ("appointments", "client_external_id"),
            ("appointments", "staff_member_external_id"),
            ("appointments", "service_external_id"),
        ]
        for section, field in cases:
            with self.subTest(section=section, field=field):
                data = _minimal_data()
                data[section][0][field] = "x" * (LIMIT + 1)
                with self.assertRaises(CommandError) as ctx:
                    self.run_data(data)
                self.assertIn(section, str(ctx.exception))
                self.assertIn(field, str(ctx.exception))
                self.assertIn(
                    str(data[section][0]["id"]), str(ctx.exception))
                self.assert_zero_written()
                # No truncated identity was stored anywhere.
                truncated = "x" * LIMIT
                self.assertFalse(
                    Client.objects.filter(external_id=truncated).exists())
                self.assertFalse(
                    Service.objects.filter(external_id=truncated).exists())
                self.assertFalse(Appointment.objects.filter(
                    external_id=truncated).exists())

    def test_two_overlong_ids_sharing_prefix_do_not_collide(self):
        data = _minimal_data()
        prefix = "y" * LIMIT
        second = dict(data["clients"][0])
        second["id"] = 51
        second["external_id"] = prefix + "B"
        data["clients"][0]["external_id"] = prefix + "A"
        data["clients"].append(second)
        with self.assertRaises(CommandError):
            self.run_data(data)
        self.assert_zero_written()
        self.assertFalse(
            Client.objects.filter(external_id=prefix).exists())

    def test_at_limit_external_id_imports_exactly(self):
        data = _minimal_data()
        exact = "z" * LIMIT
        data["clients"][0]["external_id"] = exact
        data["appointments"][0]["client_external_id"] = exact
        self.run_data(data)
        self.assertEqual(Client.objects.get().external_id, exact)

    def test_numeric_ids_stored_and_matched_as_str(self):
        data = _minimal_data()
        # Numeric external ids; string spellings on the links, and
        # mixed int/str spellings for the file-local references.
        data["services"][0]["external_id"] = 4201
        data["clients"][0]["external_id"] = 4202
        data["staff_members"][0]["external_id"] = 4203
        data["appointments"][0]["external_id"] = 4204
        data["appointments"][0]["client_external_id"] = "4202"
        data["appointments"][0]["staff_member_external_id"] = "4203"
        data["appointments"][0]["service_external_id"] = "4201"
        data["service_categories"][0]["salon_id"] = "1"
        data["services"][0]["category_id"] = "10"
        data["clients"][0]["salon_id"] = "1"
        data["appointments"][0]["client_id"] = "50"
        self.run_data(data)
        self.assertEqual(Service.objects.get().external_id, "4201")
        self.assertEqual(Client.objects.get().external_id, "4202")
        self.assertEqual(StaffMember.objects.get().external_id, "4203")
        appt = Appointment.objects.get()
        self.assertEqual(appt.external_id, "4204")
        self.assertEqual(appt.client.external_id, "4202")
        self.assertEqual(appt.staff_member.external_id, "4203")
        self.assertEqual(appt.service.external_id, "4201")
        # Re-import with string spellings updates in place.
        data["services"][0]["external_id"] = "4201"
        data["clients"][0]["external_id"] = "4202"
        data["staff_members"][0]["external_id"] = "4203"
        data["appointments"][0]["external_id"] = "4204"
        self.run_data(data)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Appointment.objects.count(), 1)

    def test_export_shaped_fixture_imports_identically(self):
        out = self.run_data(_minimal_data())
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertEqual(Salon.objects.get().name, "TF6 Salon")
        self.assertEqual(Service.objects.get().external_id, "svc-1")
        self.assertEqual(
            ServicePrice.objects.get().amount, Decimal("85.00"))
        self.assertEqual(Client.objects.get().external_id, "cli-1")
        self.assertEqual(StaffMember.objects.get().external_id, "staff-1")
        appt = Appointment.objects.get()
        self.assertEqual(appt.external_id, "appt-1")
        self.assertEqual(appt.client.external_id, "cli-1")
        self.assertEqual(appt.service.external_id, "svc-1")


ALL_MODELS = (Salon, ServiceCategory, Service, StaffLevel, ServicePrice,
              Client, ClientNote, StaffMember, Appointment,
              AppointmentNote)


def _dry_fixture():
    """_minimal_data plus one note per note section (synthetic)."""
    data = _minimal_data()
    data["client_notes"] = [
        {"id": 90, "client_id": 50, "body": "Prefers quiet.",
         "author_name": "Front Desk",
         "created_at": "2026-01-01T09:00:00+00:00"}]
    data["appointment_notes"] = [
        {"id": 91, "appointment_id": 70, "body": "Arrives early.",
         "author_name": "Front Desk",
         "created_at": "2026-01-01T09:00:00+00:00"}]
    return data


class ImportSalonDataDryRunTests(TestCase):
    """TF-12: --dry-run reports per section, writes nothing."""

    def write_data(self, data):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, fh)
        fh.close()
        return fh.name

    def run_dry(self, data):
        out = io.StringIO()
        call_command("import_salon_data", self.write_data(data),
                     dry_run=True, stdout=out)
        return json.loads(out.getvalue())

    def assert_all_zero(self):
        for model in ALL_MODELS:
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def test_dry_run_creates_zero_rows_in_every_model(self):
        fixture = _dry_fixture()
        reports = self.run_dry(fixture)
        self.assert_all_zero()
        self.assertEqual(set(reports), {
            "salons", "service_categories", "services", "staff_levels",
            "service_prices", "clients", "client_notes", "staff_members",
            "appointments", "appointment_notes", "products",
            "roster_patterns", "shift_overrides", "sales",
            "sale_items", "sale_payments", "stock_movements",
            "attendance_records", "price_changes", "refunds", "breaks", "cashups", "receipts", "reminder_sends"})
        for section, report in reports.items():
            self.assertEqual(report["source"], section)
            self.assertEqual(
                report["record_count"], len(fixture.get(section, [])))

    def test_dry_run_names_unmapped_key_planted_in_a_section(self):
        data = _dry_fixture()
        data["clients"][0]["legacy_loyalty_code"] = "GOLD-9"
        data["salons"][0]["legacy_region"] = "north"
        reports = self.run_dry(data)
        self.assertIn("legacy_loyalty_code",
                      reports["clients"]["unmapped_keys"])
        self.assertIn("legacy_region",
                      reports["salons"]["unmapped_keys"])
        self.assertNotIn("legacy_loyalty_code",
                         reports["services"]["unmapped_keys"])
        self.assert_all_zero()

    def test_dry_run_per_section_absence_counts_are_correct(self):
        data = _dry_fixture()
        # clients.email: "" (row 1) / null (row 2) / missing (row 3)
        # / valued (row 4) — three distinct absence buckets.
        base = data["clients"][0]
        for i, email in ((51, None), (53, "ada2@example.com")):
            row = dict(base, id=i, external_id=f"cli-{i}", email=email)
            data["clients"].append(row)
        row = dict(base, id=52, external_id="cli-52")
        del row["email"]
        data["clients"].append(row)
        # services.description: "" on the only row; appointments
        # price_override: explicit null on the only row.
        reports = self.run_dry(data)
        email = reports["clients"]["fields"]["email"]
        self.assertEqual(
            (email["null"], email["missing"], email["empty_string"],
             email["valued"], email["present"]), (1, 1, 1, 1, 3))
        desc = reports["services"]["fields"]["description"]
        self.assertEqual(
            (desc["null"], desc["missing"], desc["empty_string"]),
            (0, 0, 1))
        price = reports["appointments"]["fields"]["price_override"]
        self.assertEqual(
            (price["null"], price["missing"], price["empty_string"]),
            (1, 0, 0))
        self.assert_all_zero()

    def test_normal_import_of_same_fixture_still_works(self):
        data = _dry_fixture()
        data["clients"][0]["legacy_loyalty_code"] = "GOLD-9"
        path = self.write_data(data)
        self.run_dry(data)
        self.assert_all_zero()
        out = io.StringIO()
        call_command("import_salon_data", path, stdout=out)
        self.assertIn("IMPORT_SUMMARY", out.getvalue())
        self.assertIn("clients.legacy_loyalty_code", out.getvalue())
        for model in ALL_MODELS:
            self.assertEqual(model.objects.count(), 1, model.__name__)
        self.assertEqual(Client.objects.get().external_id, "cli-1")
        self.assertEqual(Appointment.objects.get().external_id, "appt-1")


class ImportSalonDataPayloadTests(TestCase):
    """Payload leg: salon_data round-trip preserves payloads verbatim."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Payload Restore Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.service_payload = {"z_key": 1, "a_key": {"nested": [1, 2]}}
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-p", service_minutes=45,
            payload=self.service_payload)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6")
        ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"))
        self.client_payload = {"legacy": {"id": 7, "tags": ["x", "y"]}}
        self.client = Client.objects.create(
            salon=self.salon, external_id="cli-p", first_name="Ada",
            last_name="Optin", payload=self.client_payload)
        self.staff = StaffMember.objects.create(
            salon=self.salon, external_id="staff-p",
            display_name="Stylist One", staff_level=self.level)
        self.start = datetime(2026, 11, 2, 14, 0,
                              tzinfo=dt_timezone.utc)
        self.appt_payload = {"price": "85.00", "source_ref": "r-1"}
        self.appt = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, external_id="appt-p",
            start=self.start, end=self.start + timedelta(minutes=45),
            payload=self.appt_payload)

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

    @staticmethod
    def _digest(payload):
        import hashlib
        return hashlib.sha256(json.dumps(
            payload, sort_keys=True).encode()).hexdigest()

    def test_round_trip_preserves_payloads_exactly(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        out = self.run_import(path)
        # Payload is known, not dropped.
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Service.objects.count(), 1)
        self.assertEqual(Appointment.objects.count(), 1)
        client = Client.objects.get(external_id="cli-p")
        service = Service.objects.get(external_id="svc-p")
        appt = Appointment.objects.get(external_id="appt-p")
        self.assertEqual(client.payload, self.client_payload)
        self.assertEqual(service.payload, self.service_payload)
        self.assertEqual(appt.payload, self.appt_payload)
        self.assertEqual(
            self._digest(client.payload), self._digest(self.client_payload))
        self.assertEqual(
            self._digest(service.payload),
            self._digest(self.service_payload))
        self.assertEqual(
            self._digest(appt.payload), self._digest(self.appt_payload))

    def test_export_without_payload_keys_imports_cleanly_as_before(self):
        path, data = self.export_data()
        for section in ("clients", "services", "appointments"):
            for row in data[section]:
                row.pop("payload", None)
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(Client.objects.get().payload, {})
        self.assertEqual(Service.objects.get().payload, {})
        self.assertEqual(Appointment.objects.get().payload, {})

    def test_reimport_with_payload_updates_in_place(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Appointment.objects.count(), 1)
        self.assertEqual(
            Client.objects.get().payload, self.client_payload)


class ImportSalonDataProductsTests(TestCase):
    """Products leg: salon_data round-trip preserves products exactly."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Product Restore Salon")
        self.payload = {"legacy": {"id": 11, "tags": ["retail"]}}
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SKU-1",
            barcode="012345678905", price=Decimal("24.50"),
            cost_price=Decimal("10.25"), active=False,
            external_id="prod-1", brand_name="BrandCo",
            category_name="Hair Care", product_type="retail",
            payload=self.payload)
        self.plain = Product.objects.create(
            salon=self.salon, name="Comb", price=Decimal("5.00"))

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

    @staticmethod
    def _digest(payload):
        import hashlib
        return hashlib.sha256(json.dumps(
            payload, sort_keys=True).encode()).hexdigest()

    def test_round_trip_preserves_all_product_fields_and_payload(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(Product.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("products=2", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(Product.objects.count(), 2)
        restored = Product.objects.get(external_id="prod-1")
        self.assertEqual(restored.salon.name, "Product Restore Salon")
        self.assertEqual(restored.name, "Shampoo")
        self.assertEqual(restored.sku, "SKU-1")
        self.assertEqual(restored.barcode, "012345678905")
        self.assertEqual(restored.price, Decimal("24.50"))
        self.assertEqual(restored.cost_price, Decimal("10.25"))
        self.assertFalse(restored.active)
        self.assertEqual(restored.brand_name, "BrandCo")
        self.assertEqual(restored.category_name, "Hair Care")
        self.assertEqual(restored.product_type, "retail")
        self.assertEqual(restored.payload, self.payload)
        self.assertEqual(
            self._digest(restored.payload), self._digest(self.payload))
        plain = Product.objects.get(name="Comb")
        self.assertEqual(plain.price, Decimal("5.00"))
        self.assertIsNone(plain.cost_price)
        self.assertEqual(plain.payload, {})

    def test_reimport_products_is_idempotent_and_updates_in_place(self):
        path, data = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(Product.objects.count(), 2)
        row = next(p for p in data["products"]
                   if p["external_id"] == "prod-1")
        row["price"] = "26.00"
        self.write_data(path, data)
        self.run_import(path)
        self.assertEqual(Product.objects.count(), 2)
        self.assertEqual(
            Product.objects.get(external_id="prod-1").price,
            Decimal("26.00"))

    def test_missing_products_section_imports_exactly_as_before(self):
        path, data = self.export_data()
        del data["products"]
        del data["counts"]["products"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("IMPORT_SUMMARY", out)
        self.assertIn("products=0", out)
        self.assertEqual(Salon.objects.count(), 1)
        self.assertEqual(Product.objects.count(), 0)

    def test_unknown_key_in_products_named_not_dropped_silently(self):
        path, data = self.export_data()
        data["products"][0]["legacy_vendor_code"] = "V-9"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("products.legacy_vendor_code", out)
        self.assertEqual(Product.objects.count(), 2)

    def test_bad_product_price_fails_closed_with_zero_writes(self):
        path, data = self.export_data()
        data["products"][0]["price"] = "not-money"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Product.objects.count(), 0)


class ImportSalonDataRosterTests(TestCase):
    """Roster leg: salon_data round-trip preserves the roster exactly."""

    def setUp(self):
        self.salon = Salon.objects.create(name="Roster Restore Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            external_id="staff-r")
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=0,
            start_time=time(9, 0), end_time=time(17, 0))
        RosterPattern.objects.create(
            staff_member=self.staff, weekday=5,
            start_time=time(10, 0), end_time=time(14, 0), active=False)
        ShiftOverride.objects.create(
            staff_member=self.staff, date=date(2026, 11, 7), is_off=True)
        ShiftOverride.objects.create(
            staff_member=self.staff, date=date(2026, 11, 14),
            is_off=False, start_time=time(9, 0), end_time=time(13, 0))

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

    def test_round_trip_preserves_all_roster_fields(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(RosterPattern.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("roster_patterns=2", out)
        self.assertIn("shift_overrides=2", out)
        staff = StaffMember.objects.get(external_id="staff-r")
        patterns = {(p.weekday, p.start_time, p.end_time, p.active)
                    for p in RosterPattern.objects.filter(
                        staff_member=staff)}
        self.assertEqual(patterns, {
            (0, time(9, 0), time(17, 0), True),
            (5, time(10, 0), time(14, 0), False),
        })
        overrides = {(o.date, o.is_off, o.start_time, o.end_time)
                     for o in ShiftOverride.objects.filter(
                         staff_member=staff)}
        self.assertEqual(overrides, {
            (date(2026, 11, 7), True, None, None),
            (date(2026, 11, 14), False, time(9, 0), time(13, 0)),
        })

    def test_reimport_roster_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(RosterPattern.objects.count(), 2)
        self.assertEqual(ShiftOverride.objects.count(), 2)

    def test_missing_roster_sections_import_exactly_as_before(self):
        path, data = self.export_data()
        for section in ("roster_patterns", "shift_overrides"):
            del data[section]
            del data["counts"][section]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("roster_patterns=0", out)
        self.assertIn("shift_overrides=0", out)
        self.assertEqual(RosterPattern.objects.count(), 0)
        self.assertEqual(ShiftOverride.objects.count(), 0)

    def test_non_bool_is_off_fails_closed_with_zero_writes(self):
        path, data = self.export_data()
        data["shift_overrides"][0]["is_off"] = "false"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(RosterPattern.objects.count(), 0)
        self.assertEqual(ShiftOverride.objects.count(), 0)

    def test_unknown_key_in_roster_patterns_named_not_dropped(self):
        path, data = self.export_data()
        data["roster_patterns"][0]["legacy_roster_code"] = "R-9"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("roster_patterns.legacy_roster_code", out)
        self.assertEqual(RosterPattern.objects.count(), 2)


class ImportSalonDataSalesTests(TestCase):
    """Sales leg: salon_data round-trip preserves sales exactly.

    Payment.provider_reference is omitted by the exporter, so a
    restored payment carries the model default ("") — provider ids
    never travel in salon_data (provider-agnostic founding rule).
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Sales Restore Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-s", service_minutes=45)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", price=Decimal("24.50"),
            external_id="prod-s")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Ada", last_name="Optin",
            external_id="cli-s")
        self.sale = Sale.objects.create(
            salon=self.salon, client=self.client,
            status=Sale.Status.COMPLETED)
        SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.SERVICE,
            service=self.service, description="Single Process",
            quantity=1, unit_price=Decimal("85.00"))
        SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.PRODUCT,
            product=self.product, description="Shampoo",
            quantity=2, unit_price=Decimal("24.50"))
        Payment.objects.create(
            sale=self.sale, method=Payment.Method.CASH,
            amount=Decimal("134.00"), status=Payment.Status.COMPLETED,
            provider_reference="PROV-SECRET-1")
        Sale.objects.create(salon=self.salon)

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

    def test_round_trip_preserves_sales_items_and_payments(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(Sale.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("sales=2", out)
        self.assertIn("sale_items=2", out)
        self.assertIn("sale_payments=1", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(Sale.objects.count(), 2)
        sale = Sale.objects.get(status=Sale.Status.COMPLETED)
        self.assertEqual(sale.salon.name, "Sales Restore Salon")
        self.assertEqual(sale.client.external_id, "cli-s")
        self.assertEqual(sale.total, Decimal("134.00"))
        items = {i.kind: i for i in sale.items.all()}
        self.assertEqual(items["service"].service.external_id, "svc-s")
        self.assertEqual(items["service"].unit_price, Decimal("85.00"))
        self.assertEqual(items["product"].product.external_id, "prod-s")
        self.assertEqual(items["product"].quantity, 2)
        pay = sale.payments.get()
        self.assertEqual(pay.method, "cash")
        self.assertEqual(pay.amount, Decimal("134.00"))
        self.assertEqual(pay.status, "completed")
        # Provider identifier did not travel.
        self.assertEqual(pay.provider_reference, "")

    def test_reimport_sales_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(Sale.objects.count(), 2)
        self.assertEqual(SaleItem.objects.count(), 2)
        self.assertEqual(Payment.objects.count(), 1)

    def test_missing_sales_sections_import_exactly_as_before(self):
        path, data = self.export_data()
        for section in ("sales", "sale_items", "sale_payments"):
            del data[section]
            del data["counts"][section]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("sales=0", out)
        self.assertIn("sale_items=0", out)
        self.assertIn("sale_payments=0", out)
        self.assertEqual(Sale.objects.count(), 0)

    def test_provider_reference_in_file_named_dropped_not_imported(self):
        path, data = self.export_data()
        data["sale_payments"][0]["provider_reference"] = "PROV-X"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("sale_payments.provider_reference", out)
        self.assertEqual(Payment.objects.get().provider_reference, "")

    def test_bad_payment_amount_fails_closed_zero_writes(self):
        # TF-3: money is Decimal parsed from its string spelling;
        # a non-numeric amount fails phase 1 entirely.
        path, data = self.export_data()
        data["sale_payments"][0]["amount"] = "not-money"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Sale.objects.count(), 0)
        self.assertEqual(Payment.objects.count(), 0)

    def test_dangling_sale_ref_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["sale_items"][0]["sale_id"] = 999999
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Sale.objects.count(), 0)


class ImportSalonDataStockMovementsTests(TestCase):
    """Stock movements leg: round-trip preserves movements exactly.

    Idempotency key: (product, kind, quantity_delta, note,
    created_at) — created_at anchors otherwise identical rows.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Stock Restore Salon")
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", price=Decimal("24.50"),
            external_id="prod-m")
        StockMovement.objects.create(
            product=self.product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=10, note="Delivery")
        StockMovement.objects.create(
            product=self.product, kind=StockMovement.Kind.SALE,
            quantity_delta=-1)

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

    def test_round_trip_preserves_stock_movements(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(StockMovement.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("stock_movements=2", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(StockMovement.objects.count(), 2)
        restored = Product.objects.get(external_id="prod-m")
        self.assertEqual(restored.current_stock, 9)
        by_kind = {m.kind: m for m in restored.stock_movements.all()}
        self.assertEqual(by_kind["receive"].quantity_delta, 10)
        self.assertEqual(by_kind["receive"].note, "Delivery")
        self.assertEqual(by_kind["sale"].quantity_delta, -1)

    def test_reimport_stock_movements_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(StockMovement.objects.count(), 2)
        self.assertEqual(
            Product.objects.get(external_id="prod-m").current_stock, 9)

    def test_missing_stock_movements_section_imports_as_before(self):
        path, data = self.export_data()
        del data["stock_movements"]
        del data["counts"]["stock_movements"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("stock_movements=0", out)
        self.assertEqual(StockMovement.objects.count(), 0)
        self.assertEqual(Product.objects.count(), 1)

    def test_unknown_key_in_stock_movements_named_not_dropped(self):
        path, data = self.export_data()
        data["stock_movements"][0]["legacy_bin"] = "B-2"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("stock_movements.legacy_bin", out)
        self.assertEqual(StockMovement.objects.count(), 2)

    def test_dangling_product_ref_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["stock_movements"][0]["product_id"] = 999999
        data["stock_movements"][0]["product_external_id"] = "nope"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_overlong_product_external_id_fails_closed(self):
        path, data = self.export_data()
        data["stock_movements"][0]["product_external_id"] = "x" * 65
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_bad_quantity_delta_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["stock_movements"][0]["quantity_delta"] = 1.5
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(StockMovement.objects.count(), 0)


class ImportSalonDataAttendanceRecordsTests(TestCase):
    """Attendance leg: round-trip preserves the event log exactly.

    Idempotency key: (staff_member, recorded_at, event_type) —
    recorded_at is the anchor, as created_at is for sales.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Clock Restore Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            external_id="staff-a")
        AttendanceRecord.objects.create(
            staff_member=self.staff,
            event_type=AttendanceRecord.EventType.CHECK_IN,
            recorded_at=datetime(2026, 10, 3, 9, 0,
                                 tzinfo=dt_timezone.utc),
            note="On time")
        AttendanceRecord.objects.create(
            staff_member=self.staff,
            event_type=AttendanceRecord.EventType.CHECK_OUT,
            recorded_at=datetime(2026, 10, 3, 17, 0,
                                 tzinfo=dt_timezone.utc))

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

    def test_round_trip_preserves_attendance_records(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("attendance_records=2", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(AttendanceRecord.objects.count(), 2)
        restored = StaffMember.objects.get(external_id="staff-a")
        by_type = {r.event_type: r
                   for r in restored.attendance_records.all()}
        self.assertEqual(
            by_type["check_in"].recorded_at,
            datetime(2026, 10, 3, 9, 0, tzinfo=dt_timezone.utc))
        self.assertEqual(by_type["check_in"].note, "On time")
        self.assertEqual(by_type["check_out"].note, "")
        self.assertTrue(restored.is_checked_in() is False)

    def test_reimport_attendance_records_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(AttendanceRecord.objects.count(), 2)

    def test_missing_attendance_section_imports_as_before(self):
        path, data = self.export_data()
        del data["attendance_records"]
        del data["counts"]["attendance_records"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("attendance_records=0", out)
        self.assertEqual(AttendanceRecord.objects.count(), 0)
        self.assertEqual(StaffMember.objects.count(), 1)

    def test_unknown_key_in_attendance_named_not_dropped(self):
        path, data = self.export_data()
        data["attendance_records"][0]["legacy_badge"] = "B-7"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("attendance_records.legacy_badge", out)
        self.assertEqual(AttendanceRecord.objects.count(), 2)

    def test_dangling_staff_ref_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["attendance_records"][0]["staff_member_id"] = 999999
        data["attendance_records"][0]["staff_member_external_id"] = "nope"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_overlong_staff_external_id_fails_closed(self):
        path, data = self.export_data()
        data["attendance_records"][0][
            "staff_member_external_id"] = "x" * 65
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_naive_recorded_at_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["attendance_records"][0]["recorded_at"] = \
            "2026-10-03T09:00:00"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(AttendanceRecord.objects.count(), 0)

    def test_bad_event_type_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["attendance_records"][0]["event_type"] = "clock_in"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(AttendanceRecord.objects.count(), 0)


class ImportSalonDataPriceChangesTests(TestCase):
    """Price changes leg: round-trip preserves the audit trail.

    Idempotency natural key: (service_price, changed_at,
    old_amount, new_amount, changed_by, note) — append-only
    history is get_or_create'd, never updated, never duplicated.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Audit Restore Salon")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color")
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-pc", service_minutes=45)
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6", sort_order=6)
        self.price = ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"))
        self.rise = PriceChange.objects.create(
            service_price=self.price, old_amount=Decimal("75.00"),
            new_amount=Decimal("85.00"), changed_by="Manager",
            note="Annual rise")
        self.first = PriceChange.objects.create(
            service_price=self.price, old_amount=None,
            new_amount=Decimal("75.00"))

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

    def test_round_trip_preserves_price_changes_exactly(self):
        expected_times = sorted(
            c.changed_at for c in (self.rise, self.first))
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(PriceChange.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("price_changes=2", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(PriceChange.objects.count(), 2)
        restored_price = ServicePrice.objects.get(
            service__external_id="svc-pc")
        by_new = {c.new_amount: c
                  for c in restored_price.changes.all()}
        rise = by_new[Decimal("85.00")]
        self.assertEqual(rise.old_amount, Decimal("75.00"))
        self.assertEqual(str(rise.new_amount), "85.00")
        self.assertEqual(rise.changed_by, "Manager")
        self.assertEqual(rise.note, "Annual rise")
        self.assertIsNone(by_new[Decimal("75.00")].old_amount)
        self.assertEqual(
            sorted(c.changed_at for c in restored_price.changes.all()),
            expected_times)

    def test_reimport_price_changes_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(PriceChange.objects.count(), 2)

    def test_missing_price_changes_section_imports_as_before(self):
        path, data = self.export_data()
        del data["price_changes"]
        del data["counts"]["price_changes"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("price_changes=0", out)
        self.assertEqual(PriceChange.objects.count(), 0)
        self.assertEqual(ServicePrice.objects.count(), 1)

    def test_unknown_key_in_price_changes_named_not_dropped(self):
        path, data = self.export_data()
        data["price_changes"][0]["legacy_reason"] = "promo"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("price_changes.legacy_reason", out)
        self.assertEqual(PriceChange.objects.count(), 2)

    def test_dangling_price_ref_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["price_changes"][0]["service_price_id"] = 999999
        data["price_changes"][0]["service_external_id"] = "nope"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(PriceChange.objects.count(), 0)

    def test_naive_changed_at_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["price_changes"][0]["changed_at"] = "2026-10-03T09:00:00"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(PriceChange.objects.count(), 0)

    def test_dry_run_reports_price_changes_and_writes_nothing(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        out = io.StringIO()
        call_command("import_salon_data", path, dry_run=True, stdout=out)
        reports = json.loads(out.getvalue())
        self.assertEqual(reports["price_changes"]["record_count"], 2)
        self.assertEqual(reports["price_changes"]["unmapped_keys"], [])
        self.assertEqual(PriceChange.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 0)


class ImportSalonDataRefundsTests(TestCase):
    """Refunds leg: round-trip preserves refunds exactly.

    Idempotency natural key: (sale, amount, reason, tender,
    created_at) — append-only history is get_or_create'd,
    never updated, never duplicated.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Refund Restore Salon")
        self.sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        self.refund = Refund.objects.create(
            sale=self.sale, amount=Decimal("20.50"),
            reason="Client unhappy", tender=Payment.Method.CASH)
        self.other_refund = Refund.objects.create(
            sale=self.sale, amount=Decimal("5.00"),
            tender=Payment.Method.EXTERNAL)

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

    def test_round_trip_preserves_refunds_exactly(self):
        expected_times = sorted(
            r.created_at for r in (self.refund, self.other_refund))
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(Refund.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("refunds=2", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(Refund.objects.count(), 2)
        sale = Sale.objects.get()
        by_amount = {r.amount: r for r in sale.refunds.all()}
        row = by_amount[Decimal("20.50")]
        self.assertEqual(str(row.amount), "20.50")
        self.assertEqual(row.reason, "Client unhappy")
        self.assertEqual(row.tender, "cash")
        self.assertEqual(by_amount[Decimal("5.00")].tender, "external")
        self.assertEqual(
            sorted(r.created_at for r in sale.refunds.all()),
            expected_times)

    def test_reimport_refunds_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(Refund.objects.count(), 2)

    def test_missing_refunds_section_imports_as_before(self):
        path, data = self.export_data()
        del data["refunds"]
        del data["counts"]["refunds"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("refunds=0", out)
        self.assertEqual(Refund.objects.count(), 0)
        self.assertEqual(Sale.objects.count(), 1)

    def test_unknown_key_in_refunds_named_not_dropped(self):
        path, data = self.export_data()
        data["refunds"][0]["legacy_code"] = "X"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("refunds.legacy_code", out)
        self.assertEqual(Refund.objects.count(), 2)

    def test_dangling_sale_ref_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["refunds"][0]["sale_id"] = 999999
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Refund.objects.count(), 0)

    def test_naive_created_at_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["refunds"][0]["created_at"] = "2026-10-03T09:00:00"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Refund.objects.count(), 0)

    def test_dry_run_reports_refunds_and_writes_nothing(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        out = io.StringIO()
        call_command("import_salon_data", path, dry_run=True, stdout=out)
        reports = json.loads(out.getvalue())
        self.assertEqual(reports["refunds"]["record_count"], 2)
        self.assertEqual(reports["refunds"]["unmapped_keys"], [])
        self.assertEqual(Refund.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 0)


class ImportSalonDataBreaksTests(TestCase):
    """Breaks leg: round-trip preserves breaks exactly.

    Idempotency natural key: (staff_member, start, end) —
    get_or_create with paid as a default, never duplicated.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Break Restore Salon")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            external_id="staff-a")
        self.paid_break = Break.objects.create(
            staff_member=self.staff,
            start=datetime(2026, 10, 3, 12, 0, tzinfo=dt_timezone.utc),
            end=datetime(2026, 10, 3, 12, 30, tzinfo=dt_timezone.utc),
            paid=True)
        self.unpaid_break = Break.objects.create(
            staff_member=self.staff,
            start=datetime(2026, 10, 3, 15, 0, tzinfo=dt_timezone.utc),
            end=datetime(2026, 10, 3, 15, 15, tzinfo=dt_timezone.utc),
            paid=False)

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

    def test_round_trip_preserves_breaks_exactly(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(Break.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("breaks=2", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(Break.objects.count(), 2)
        restored = StaffMember.objects.get(external_id="staff-a")
        by_start = {b.start: b for b in restored.breaks.all()}
        paid = by_start[datetime(2026, 10, 3, 12, 0, tzinfo=dt_timezone.utc)]
        self.assertEqual(paid.end, datetime(2026, 10, 3, 12, 30, tzinfo=dt_timezone.utc))
        self.assertIs(paid.paid, True)
        unpaid = by_start[datetime(2026, 10, 3, 15, 0, tzinfo=dt_timezone.utc)]
        self.assertEqual(unpaid.end, datetime(2026, 10, 3, 15, 15, tzinfo=dt_timezone.utc))
        self.assertIs(unpaid.paid, False)

    def test_reimport_breaks_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(Break.objects.count(), 2)

    def test_missing_breaks_section_imports_as_before(self):
        path, data = self.export_data()
        del data["breaks"]
        del data["counts"]["breaks"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("breaks=0", out)
        self.assertEqual(Break.objects.count(), 0)
        self.assertEqual(StaffMember.objects.count(), 1)

    def test_unknown_key_in_breaks_named_not_dropped(self):
        path, data = self.export_data()
        data["breaks"][0]["legacy_code"] = "X"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("breaks.legacy_code", out)
        self.assertEqual(Break.objects.count(), 2)

    def test_dangling_staff_ref_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["breaks"][0]["staff_member_id"] = 999999
        data["breaks"][0]["staff_member_external_id"] = "nope"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Break.objects.count(), 0)

    def test_naive_start_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["breaks"][0]["start"] = "2026-10-03T12:00:00"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Break.objects.count(), 0)

    def test_naive_end_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["breaks"][0]["end"] = "2026-10-03T12:30:00"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Break.objects.count(), 0)

    def test_non_bool_paid_fails_closed_zero_writes(self):
        path, base = self.export_data()
        for bad in ("true", 1, 0):
            data = json.loads(json.dumps(base))
            data["breaks"][0]["paid"] = bad
            self.write_data(path, data)
            Salon.objects.all().delete()
            with self.assertRaises(CommandError):
                call_command("import_salon_data", path)
            self.assertEqual(Salon.objects.count(), 0)
            self.assertEqual(Break.objects.count(), 0)

    def test_missing_paid_fails_closed_zero_writes(self):
        path, data = self.export_data()
        del data["breaks"][0]["paid"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Break.objects.count(), 0)

    def test_null_paid_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["breaks"][0]["paid"] = None
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Break.objects.count(), 0)

    def test_dry_run_reports_breaks_and_writes_nothing(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        out = io.StringIO()
        call_command("import_salon_data", path, dry_run=True, stdout=out)
        reports = json.loads(out.getvalue())
        self.assertEqual(reports["breaks"]["record_count"], 2)
        self.assertEqual(reports["breaks"]["unmapped_keys"], [])
        self.assertEqual(Break.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 0)


class ImportSalonDataCashupsTests(TestCase):
    """Cashups leg: round-trip preserves cashups exactly.

    Idempotency natural key: (salon, period_start, period_end,
    created_at) — a snapshot is get_or_create'd, never updated,
    never duplicated.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Cashup Restore Salon")
        self.start = datetime(2026, 10, 3, 9, 0, tzinfo=dt_timezone.utc)
        self.end = datetime(2026, 10, 3, 17, 0, tzinfo=dt_timezone.utc)
        self.cashup = Cashup.objects.create(
            salon=self.salon, period_start=self.start,
            period_end=self.end,
            tender_totals={"cash": "85.00", "external": "20.50"},
            total=Decimal("105.50"), note="Morning close")
        self.other_cashup = Cashup.objects.create(
            salon=self.salon, period_start=self.end,
            period_end=datetime(2026, 10, 3, 21, 0,
                                 tzinfo=dt_timezone.utc),
            tender_totals={"cash": "10.00"}, total=Decimal("10.00"))

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

    def test_round_trip_preserves_cashups_exactly(self):
        expected_times = sorted(
            c.created_at for c in (self.cashup, self.other_cashup))
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(Cashup.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("cashups=2", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(Cashup.objects.count(), 2)
        salon = Salon.objects.get()
        by_total = {c.total: c for c in salon.cashups.all()}
        row = by_total[Decimal("105.50")]
        self.assertEqual(str(row.total), "105.50")
        self.assertEqual(
            row.tender_totals, {"cash": "85.00", "external": "20.50"})
        self.assertEqual(row.period_start, self.start)
        self.assertEqual(row.period_end, self.end)
        self.assertEqual(row.note, "Morning close")
        self.assertEqual(
            sorted(c.created_at for c in salon.cashups.all()),
            expected_times)

    def test_reimport_cashups_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(Cashup.objects.count(), 2)

    def test_missing_cashups_section_imports_as_before(self):
        path, data = self.export_data()
        del data["cashups"]
        del data["counts"]["cashups"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("cashups=0", out)
        self.assertEqual(Cashup.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 1)

    def test_unknown_key_in_cashups_named_not_dropped(self):
        path, data = self.export_data()
        data["cashups"][0]["legacy_code"] = "X"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("cashups.legacy_code", out)
        self.assertEqual(Cashup.objects.count(), 2)

    def test_dangling_salon_ref_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["cashups"][0]["salon_id"] = 999999
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Cashup.objects.count(), 0)

    def test_naive_period_start_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["cashups"][0]["period_start"] = "2026-10-03T09:00:00"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Cashup.objects.count(), 0)

    def test_bad_tender_totals_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["cashups"][0]["tender_totals"] = {"cash": "not-a-number"}
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Cashup.objects.count(), 0)

    def test_bad_total_fails_closed_zero_writes(self):
        path, data = self.export_data()
        data["cashups"][0]["total"] = "not-a-number"
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Cashup.objects.count(), 0)

    def test_dry_run_reports_cashups_and_writes_nothing(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        out = io.StringIO()
        call_command("import_salon_data", path, dry_run=True, stdout=out)
        reports = json.loads(out.getvalue())
        self.assertEqual(reports["cashups"]["record_count"], 2)
        self.assertEqual(reports["cashups"]["unmapped_keys"], [])
        self.assertEqual(Cashup.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 0)


class ImportSalonDataReceiptsTests(TestCase):
    """Receipts leg: round-trip preserves receipts exactly.

    Idempotency natural key: (sale) — the OneToOne — a snapshot
    is get_or_create'd on its sale, never updated, never duplicated.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Receipt Restore Salon")
        self.sale = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        self.sent_at = datetime(2026, 10, 3, 17, 5, tzinfo=dt_timezone.utc)
        self.receipt = Receipt.objects.create(
            sale=self.sale, salon_name="Receipt Restore Salon",
            lines=[{"description": "Single Process", "kind": "service",
                    "quantity": 1, "unit_price": "85.00",
                    "line_total": "85.00"}],
            total=Decimal("85.00"),
            tender=[{"method": "cash", "amount": "85.00",
                     "status": "completed"}],
            recipient_email="ada@example.com", sent_at=self.sent_at)
        self.sale2 = Sale.objects.create(
            salon=self.salon, status=Sale.Status.COMPLETED)
        self.receipt2 = Receipt.objects.create(
            sale=self.sale2, total=Decimal("10.00"))

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

    def fail_closed(self, mutate):
        path, data = self.export_data()
        mutate(data)
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(Receipt.objects.count(), 0)

    def test_round_trip_preserves_receipts_exactly(self):
        expected_issued = sorted(
            r.issued_at for r in (self.receipt, self.receipt2))
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(Receipt.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("receipts=2", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(Receipt.objects.count(), 2)
        sale = Sale.objects.get(receipt__total=Decimal("85.00"))
        row = sale.receipt
        self.assertEqual(str(row.total), "85.00")
        self.assertEqual(row.salon_name, "Receipt Restore Salon")
        self.assertEqual(row.lines, self.receipt.lines)
        self.assertEqual(row.tender, self.receipt.tender)
        self.assertEqual(row.recipient_email, "ada@example.com")
        self.assertEqual(row.sent_at, self.sent_at)
        self.assertEqual(
            sorted(r.issued_at for r in Receipt.objects.all()),
            expected_issued)
        self.assertIsNone(
            Receipt.objects.get(total=Decimal("10.00")).sent_at)

    def test_reimport_receipts_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(Receipt.objects.count(), 2)

    def test_missing_receipts_section_imports_as_before(self):
        path, data = self.export_data()
        del data["receipts"]
        del data["counts"]["receipts"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("receipts=0", out)
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 1)

    def test_unknown_key_in_receipts_named_not_dropped(self):
        path, data = self.export_data()
        data["receipts"][0]["legacy_code"] = "X"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("receipts.legacy_code", out)
        self.assertEqual(Receipt.objects.count(), 2)

    def test_dangling_sale_ref_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["receipts"][0].update(sale_id=999999))

    def test_naive_issued_at_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["receipts"][0].update(
                issued_at="2026-10-03T09:00:00"))

    def test_naive_sent_at_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["receipts"][0].update(
                sent_at="2026-10-03T09:00:00"))

    def test_bad_total_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["receipts"][0].update(total="not-a-number"))

    def test_lines_not_list_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["receipts"][0].update(lines="not-a-list"))

    def test_tender_not_list_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["receipts"][0].update(tender={"method": "cash"}))

    def test_dry_run_reports_receipts_and_writes_nothing(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        out = io.StringIO()
        call_command("import_salon_data", path, dry_run=True, stdout=out)
        reports = json.loads(out.getvalue())
        self.assertEqual(reports["receipts"]["record_count"], 2)
        self.assertEqual(reports["receipts"]["unmapped_keys"], [])
        self.assertEqual(Receipt.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 0)


class ImportSalonDataReminderSendsTests(TestCase):
    """Reminder sends leg: round-trip preserves sends exactly.

    Idempotency natural key: (appointment, client, channel,
    sent_at) — a send is get_or_create'd on that key, never
    updated, never duplicated.
    """

    def setUp(self):
        self.salon = Salon.objects.create(name="Reminder Restore Salon")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Ada", last_name="Optin")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One")
        self.start = datetime(2026, 11, 2, 14, 0, tzinfo=dt_timezone.utc)
        self.appt = Appointment.objects.create(
            client=self.client, staff_member=self.staff, service=None,
            start=self.start, end=self.start + timedelta(minutes=45))
        self.sent_at = datetime(2026, 10, 3, 17, 5, tzinfo=dt_timezone.utc)
        self.send = ReminderSend.objects.create(
            appointment=self.appt, client=self.client, channel="email",
            status="sent", sent_at=self.sent_at, detail="")
        self.send2 = ReminderSend.objects.create(
            appointment=self.appt, client=self.client, channel="sms",
            status="sent", sent_at=self.sent_at + timedelta(hours=1),
            detail="ref-123")

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

    def fail_closed(self, mutate):
        path, data = self.export_data()
        mutate(data)
        self.write_data(path, data)
        Salon.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("import_salon_data", path)
        self.assertEqual(Salon.objects.count(), 0)
        self.assertEqual(ReminderSend.objects.count(), 0)

    def test_round_trip_preserves_reminder_sends_exactly(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.assertEqual(ReminderSend.objects.count(), 0)
        out = self.run_import(path)
        self.assertIn("reminder_sends=2", out)
        self.assertIn("unknown_keys=none", out)
        self.assertEqual(ReminderSend.objects.count(), 2)
        appt = Appointment.objects.get()
        client = Client.objects.get()
        by_channel = {r.channel: r for r in ReminderSend.objects.all()}
        row = by_channel["email"]
        self.assertEqual(row.appointment, appt)
        self.assertEqual(row.client, client)
        self.assertEqual(row.status, "sent")
        self.assertEqual(row.sent_at, self.sent_at)
        self.assertEqual(row.detail, "")
        self.assertEqual(by_channel["sms"].detail, "ref-123")
        self.assertEqual(
            by_channel["sms"].sent_at, self.sent_at + timedelta(hours=1))

    def test_reimport_reminder_sends_is_idempotent(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        self.run_import(path)
        self.run_import(path)
        self.assertEqual(ReminderSend.objects.count(), 2)

    def test_missing_reminder_sends_section_imports_as_before(self):
        path, data = self.export_data()
        del data["reminder_sends"]
        del data["counts"]["reminder_sends"]
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("reminder_sends=0", out)
        self.assertEqual(ReminderSend.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 1)

    def test_unknown_key_in_reminder_sends_named_not_dropped(self):
        path, data = self.export_data()
        data["reminder_sends"][0]["legacy_code"] = "X"
        self.write_data(path, data)
        Salon.objects.all().delete()
        out = self.run_import(path)
        self.assertIn("reminder_sends.legacy_code", out)
        self.assertEqual(ReminderSend.objects.count(), 2)

    def test_dangling_appointment_ref_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["reminder_sends"][0].update(
                appointment_id=999999))

    def test_dangling_client_ref_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["reminder_sends"][0].update(client_id=999999))

    def test_naive_sent_at_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["reminder_sends"][0].update(
                sent_at="2026-10-03T09:00:00"))

    def test_bad_channel_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["reminder_sends"][0].update(channel="pigeon"))

    def test_bad_status_fails_closed_zero_writes(self):
        self.fail_closed(
            lambda d: d["reminder_sends"][0].update(status="queued"))

    def test_dry_run_reports_reminder_sends_and_writes_nothing(self):
        path, _ = self.export_data()
        Salon.objects.all().delete()
        out = io.StringIO()
        call_command("import_salon_data", path, dry_run=True, stdout=out)
        reports = json.loads(out.getvalue())
        self.assertEqual(reports["reminder_sends"]["record_count"], 2)
        self.assertEqual(reports["reminder_sends"]["unmapped_keys"], [])
        self.assertEqual(ReminderSend.objects.count(), 0)
        self.assertEqual(Salon.objects.count(), 0)
