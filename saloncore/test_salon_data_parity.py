"""Bundle-vs-standalone field-parity regression tests (audit-124 rank 5).

The salon_data bundle (``export_salon_data``) and the standalone
verbatim export services grew section by section, app by app.
Twice that drift hurt: cycle 113 lost the bundle's staff_services
section in a merge, and cycle 125 found verbatim gaps between the
bundle and standalone surfaces. These tests pin the two families
together: for one synthetic record per section, the bundle row
and the standalone row for the SAME record must agree on every
shared field (same value, after money normalisation), and every
key on either side must be accounted for -- either mapped to its
counterpart (renames like ``note_id`` for the bundle's ``id`` are
declared in the field map) or listed as a documented one-sided
key with its reason. A new field added to either surface without
updating this map fails here by name, instead of drifting
silently.

Documented one-sided keys, by design:
- Bundle-only ``*_external_id`` link columns (staff_services,
  roster, shift overrides, appointments, attendance, stock
  movements, price changes, breaks, notifications, sales, sale
  items): the bundle is the restore format, so it carries the
  source-system ids needed to re-anchor rows; standalone exports
  identify the same links by internal id plus display name.
- Bundle-only staff ``pin`` / ``email``: the bundle is the
  salon's own full exit file (PINs export in plaintext, Mark
  2026-11-01); team standalone exports deliberately never carry
  credentials or contact details.
- Bundle-only sale ``client_external_id`` and receipt ``lines`` /
  ``tender`` snapshots: restore/snapshot data the standalone
  verbatim sale/receipt rows do not re-render.
- Standalone-only display/derived columns (``*_name`` labels,
  ``salon_id`` scoping columns, duplicate ``*_id`` pk aliases,
  the appointments ``price`` price-book lookup, the products
  ``stock_on_hand`` total, the receipts delivery derivation,
  the clients nested ``notes`` list): presentation of the same
  record, never a second source of truth.
- ``sale_payments``: the standalone payment export is the one
  surface that carries ``provider_reference`` verbatim; the
  bundle deliberately NEVER does (provider-agnostic founding
  rule) -- pinned by its own test below.

Every bundle section now has a standalone per-record
counterpart: ``campaign_sends`` is pinned against messaging's
per-record verbatim export (``campaign_send_detail``,
fieldnames ``id``, ``salon_id``, ``campaign_id``,
``client_id``, ``channel``, ``status``, ``sent_at``,
``detail``), with ``salon_id`` declared as a standalone-only
scoping column. ``services`` and ``service_prices`` share
one standalone surface: the joined price-book export (one
row per service+price pair).

Synthetic records only -- no real salon/client data.
"""
import io
import json
import tempfile
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.core.management import call_command
from django.test import TestCase

from bookings.export import export_appointments
from bookings.breaks_export import export_breaks
from bookings.models import Appointment, AppointmentNote, Break
from bookings.note_export import export_appointment_notes
from catalog.export import export_products
from catalog.models import Product, StockMovement
from catalog.movement_export import export_movements
from checkout.cashup_export import export_cashups
from checkout.models import Cashup, Payment, Receipt, Refund, Sale, SaleItem
from checkout.payment_export import export_payments
from checkout.receipt_export import export_receipts
from checkout.refund_export import export_refunds
from checkout.sale_export import export_sales
from checkout.sale_item_export import export_sale_items
from clients.export import export_client
from clients.models import Client, ClientNote
from clients.note_export import export_notes
from messaging.campaign_export import export_campaigns
from messaging.campaign_send_detail import (
    export_campaign_send_detail,
)
from messaging.models import Campaign, CampaignSend, ReminderSend
from messaging.send_export import export_sends
from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)
from saloncore.price_book_export import export_price_book
from saloncore.price_change_export import export_price_changes
from saloncore.salon_profile_export import export_salon_profile
from saloncore.structure_export import (
    export_service_categories,
    export_staff_levels,
)
from team.attendance_record_export import export_attendance_records
from team.capability_export import export_capability_matrix
from team.models import (
    AttendanceRecord,
    RosterPattern,
    ShiftOverride,
    StaffMember,
    StaffNotification,
    StaffService,
)
from team.notification_export import export_staff_notifications
from team.roster_export import export_roster_patterns
from team.search_export import export_staff_search_results
from team.shift_override_export import export_shift_overrides

UTC = dt_timezone.utc
WIDE = (date(2020, 1, 1), date(2030, 1, 1))
YEAR_2026 = (date(2026, 1, 1), date(2026, 12, 31))

#: Bundle sections with no standalone per-record counterpart.
#: Empty: every section is now wired to a standalone export.
NO_STANDALONE = set()


def _norm(value):
    """Normalise a value for cross-surface comparison.

    Money crosses surfaces as decimal strings formatted to two
    places on one side and ``str(Decimal)`` on the other; compare
    those by value, everything else exactly.
    """
    if isinstance(value, str):
        try:
            return ("money", Decimal(value))
        except InvalidOperation:
            return value
    return value


class SalonDataParityTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(
            name="Parity Salon", timezone="America/New_York",
            currency="USD", tagline="Hair, beautifully.",
            logo_url="https://example.com/logo.png",
            primary_color="#2F4A3C", accent_color="#C9A227")
        self.category = ServiceCategory.objects.create(
            salon=self.salon, name="Color", sort_order=1)
        self.service = Service.objects.create(
            category=self.category, name="Single Process",
            external_id="svc-1", description="Root color",
            service_minutes=45, processing_minutes=30,
            finishing_minutes=15, payload={"legacy": {"id": 3}})
        self.level = StaffLevel.objects.create(
            salon=self.salon, name="Level 6", sort_order=6)
        self.price = ServicePrice.objects.create(
            service=self.service, staff_level=self.level,
            amount=Decimal("85.00"), is_from=True)
        self.change = PriceChange.objects.create(
            service_price=self.price, old_amount=Decimal("75.00"),
            new_amount=Decimal("85.00"), changed_by="Manager",
            note="Annual rise")
        self.client = Client.objects.create(
            salon=self.salon, first_name="Ada", last_name="Parity",
            external_id="cli-1", email="ada@example.com",
            phone="555-0100", sms_opt_in=True, email_opt_in=True,
            payload={"legacy": {"id": 7}})
        self.client_note = ClientNote.objects.create(
            client=self.client, body="Prefers quiet appointments.",
            author_name="Front Desk")
        self.staff = StaffMember.objects.create(
            salon=self.salon, display_name="Stylist One",
            external_id="staff-1", staff_level=self.level,
            online_bookable=True, pin="0426",
            email="stylist@example.com")
        self.link = StaffService.objects.create(
            staff_member=self.staff, service=self.service, enabled=True)
        self.pattern = RosterPattern.objects.create(
            staff_member=self.staff, weekday=RosterPattern.Weekday.MONDAY,
            start_time=time(9, 0), end_time=time(17, 0))
        self.override = ShiftOverride.objects.create(
            staff_member=self.staff, date=date(2026, 11, 7), is_off=True)
        self.start = datetime(2026, 11, 2, 14, 0, tzinfo=UTC)
        self.appt = Appointment.objects.create(
            client=self.client, staff_member=self.staff,
            service=self.service, service_name="Single Process",
            external_id="appt-1", start=self.start,
            end=self.start + timedelta(minutes=45),
            status=Appointment.Status.CONFIRMED,
            origin=Appointment.Origin.PHONE,
            price_override=Decimal("80.00"),
            payload={"legacy": {"id": 9}})
        self.appt_note = AppointmentNote.objects.create(
            appointment=self.appt, body="Allergic to ammonia.",
            author_name="Front Desk")
        self.brk = Break.objects.create(
            staff_member=self.staff,
            start=datetime(2026, 11, 2, 12, 0, tzinfo=UTC),
            end=datetime(2026, 11, 2, 12, 30, tzinfo=UTC), paid=True)
        self.product = Product.objects.create(
            salon=self.salon, name="Shampoo", sku="SKU-1",
            barcode="012345678905", price=Decimal("24.50"),
            cost_price=Decimal("10.25"), external_id="prod-1",
            brand_name="BrandCo", category_name="Hair Care",
            product_type="retail", payload={"legacy": {"id": 11}})
        self.movement = StockMovement.objects.create(
            product=self.product, kind=StockMovement.Kind.RECEIVE,
            quantity_delta=10, note="Delivery")
        self.sale = Sale.objects.create(
            salon=self.salon, client=self.client,
            status=Sale.Status.COMPLETED,
            discount_amount=Decimal("10.00"))
        self.item = SaleItem.objects.create(
            sale=self.sale, kind=SaleItem.Kind.SERVICE,
            service=self.service, description="Single Process",
            quantity=1, unit_price=Decimal("85.00"),
            discount_amount=Decimal("5.00"))
        self.payment = Payment.objects.create(
            sale=self.sale, method=Payment.Method.CASH,
            amount=Decimal("80.00"), status=Payment.Status.COMPLETED,
            provider_reference="PROV-SECRET-1")
        self.refund = Refund.objects.create(
            sale=self.sale, amount=Decimal("20.50"),
            reason="Client unhappy", tender=Payment.Method.CASH)
        self.cashup = Cashup.objects.create(
            salon=self.salon,
            period_start=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
            period_end=datetime(2026, 10, 3, 17, 0, tzinfo=UTC),
            tender_totals={"cash": "85.00", "external": "20.50"},
            total=Decimal("105.50"), note="Morning close")
        self.receipt = Receipt.objects.create(
            sale=self.sale, salon_name="Parity Salon",
            lines=[{"description": "Single Process", "kind": "service",
                    "quantity": 1, "unit_price": "85.00",
                    "line_total": "85.00"}],
            total=Decimal("85.00"),
            tender=[{"method": "cash", "amount": "85.00",
                     "status": "completed"}],
            recipient_email="ada@example.com",
            sent_at=datetime(2026, 10, 3, 17, 5, tzinfo=UTC))
        self.attendance = AttendanceRecord.objects.create(
            staff_member=self.staff,
            event_type=AttendanceRecord.EventType.CHECK_IN,
            recorded_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
            note="On time")
        self.send = ReminderSend.objects.create(
            appointment=self.appt, client=self.client, channel="email",
            status="sent",
            sent_at=datetime(2026, 10, 3, 17, 5, tzinfo=UTC),
            detail="ref-123")
        self.campaign = Campaign.objects.create(
            salon=self.salon, name="November News",
            channel=Campaign.Channel.EMAIL, subject="Hello",
            body="News body", status=Campaign.Status.DRAFT)
        self.campaign_send = CampaignSend.objects.create(
            campaign=self.campaign, client=self.client,
            channel=Campaign.Channel.EMAIL,
            sent_at=datetime(2026, 10, 3, 17, 5, tzinfo=UTC),
            detail="ref-456")
        self.notification = StaffNotification.objects.create(
            staff_member=self.staff, appointment=self.appt,
            kind="arrived")
        self.data = self.run_bundle()

    def run_bundle(self):
        fh = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8")
        fh.close()
        call_command("export_salon_data", fh.name, stdout=io.StringIO())
        with open(fh.name, encoding="utf-8") as exported:
            return json.load(exported)

    def check(self, section, obj, rows, standalone_key, field_map,
              bundle_only=(), standalone_only=()):
        """Assert bundle/standalone parity for one record."""
        bundle_rows = [r for r in self.data[section] if r["id"] == obj.pk]
        self.assertEqual(len(bundle_rows), 1, section)
        bundle = bundle_rows[0]
        standalone_rows = [r for r in rows
                           if r[standalone_key] == obj.pk]
        self.assertEqual(len(standalone_rows), 1, section)
        standalone = standalone_rows[0]
        self.assertEqual(
            set(bundle), set(field_map) | set(bundle_only),
            f"{section}: unaccounted bundle keys")
        self.assertEqual(
            set(standalone),
            set(field_map.values()) | set(standalone_only),
            f"{section}: unaccounted standalone keys")
        for bundle_key, standalone_key_ in field_map.items():
            self.assertEqual(
                _norm(bundle[bundle_key]),
                _norm(standalone[standalone_key_]),
                f"{section}.{bundle_key} != standalone "
                f"{standalone_key_}")
        return bundle, standalone

    def specs(self):
        """(section, obj, standalone rows, id key, map, b-only, s-only)."""
        s = self.salon
        book = export_price_book(s)
        ident = lambda *keys: {k: k for k in keys}  # noqa: E731
        return [
            ("salons", self.salon, [export_salon_profile(s)], "id",
             ident("id", "name", "timezone", "currency", "tagline",
                   "logo_url", "primary_color", "accent_color",
                   "created_at", "updated_at"), (), ()),
            ("service_categories", self.category,
             export_service_categories(s), "id",
             ident("id", "salon_id", "name", "sort_order", "active"),
             (), ()),
            ("staff_levels", self.level, export_staff_levels(s), "id",
             ident("id", "salon_id", "name", "sort_order", "active"),
             (), ()),
            ("services", self.service, book, "service_id",
             {"id": "service_id", "category_id": "category_id",
              "external_id": "external_id", "name": "service_name",
              "description": "description",
              "service_minutes": "service_minutes",
              "processing_minutes": "processing_minutes",
              "finishing_minutes": "finishing_minutes",
              "active": "service_active", "payload": "payload"},
             (), ("salon_id", "category_name", "staff_level_id", "staff_level_name",
                  "service_price_id", "amount", "is_from", "price_active", "total_minutes")),
            ("service_prices", self.price, book, "service_price_id",
             {"id": "service_price_id", "service_id": "service_id",
              "staff_level_id": "staff_level_id", "amount": "amount",
              "is_from": "is_from", "active": "price_active"},
             (), ("salon_id", "category_id", "category_name", "service_name", "description",
                  "external_id", "service_minutes", "processing_minutes", "finishing_minutes",
                  "total_minutes", "service_active", "staff_level_name", "payload")),
            ("clients", self.client, [export_client(self.client)], "id",
             ident("id", "salon_id", "external_id", "first_name",
                   "last_name", "email", "phone", "sms_opt_in",
                   "email_opt_in", "active", "created_at", "payload"),
             (), ("notes",)),
            ("client_notes", self.client_note, export_notes(s), "note_id",
             {"id": "note_id", "body": "body",
              "author_name": "author_name", "created_at": "created_at"},
             ("client_id",),
             ("client_external_id", "client_first_name",
              "client_last_name")),
            ("staff_members", self.staff,
             export_staff_search_results(s), "id",
             ident("id", "salon_id", "external_id", "display_name",
                   "staff_level_id", "online_bookable", "active"),
             ("pin", "email"), ("staff_id", "staff_level_name")),
            ("staff_services", self.link, export_capability_matrix(s),
             "id",
             ident("id", "staff_member_id", "service_id", "enabled"),
             ("staff_member_external_id", "service_external_id"),
             ("salon_id", "staff_name", "service_name", "category_id", "category_name")),
            ("roster_patterns", self.pattern,
             export_roster_patterns(s, include_inactive=True), "id",
             ident("id", "staff_member_id", "weekday", "start_time",
                   "end_time", "active"),
             ("staff_member_external_id",),
             ("salon_id", "staff_name", "staff_active", "online_bookable")),
            ("shift_overrides", self.override,
             export_shift_overrides(s), "id",
             ident("id", "staff_member_id", "date", "is_off",
                   "start_time", "end_time"),
             ("staff_member_external_id",), ("salon_id", "staff_name")),
            ("appointments", self.appt,
             export_appointments(s, *YEAR_2026), "id",
             ident("id", "external_id", "client_id", "staff_member_id",
                   "service_id", "service_name", "start", "end",
                   "status", "origin", "price_override", "created_at",
                   "updated_at", "payload"),
             ("client_external_id", "staff_member_external_id", "service_external_id"),
             ("price", "service_name_snapshot")),
            ("appointment_notes", self.appt_note,
             export_appointment_notes(s), "note_id",
             {"id": "note_id", "appointment_id": "appointment_id",
              "body": "body", "author_name": "author_name",
              "created_at": "created_at"}, (), ()),
            ("products", self.product, export_products(s), "id",
             ident("id", "salon_id", "external_id", "name", "sku",
                   "barcode", "price", "cost_price", "active",
                   "brand_name", "category_name", "product_type",
                   "payload"), (), ("stock_on_hand",)),
            ("sales", self.sale, export_sales(s), "id",
             ident("id", "salon_id", "client_id", "status",
                   "discount_amount", "created_at", "completed_at",
                   "voided_at", "void_reason"),
             ("client_external_id",), ()),
            ("sale_items", self.item, export_sale_items(s), "id",
             ident("id", "sale_id", "kind", "service_id", "product_id",
                   "description", "quantity", "unit_price",
                   "discount_amount"),
             ("service_external_id", "product_external_id"), ()),
            ("sale_payments", self.payment,
             export_payments(s, *WIDE), "id",
             ident("id", "sale_id", "method", "amount", "status",
                   "created_at", "updated_at"),
             (), ("payment_id", "salon_id", "provider_reference")),
            ("attendance_records", self.attendance,
             export_attendance_records(s), "id",
             ident("id", "staff_member_id", "event_type",
                   "recorded_at", "note"),
             ("staff_member_external_id",), ("salon_id", "staff_name")),
            ("stock_movements", self.movement, export_movements(s),
             "id",
             ident("id", "product_id", "kind", "quantity_delta",
                   "note", "created_at"),
             ("product_external_id",), ("product_name", "sku", "barcode")),
            ("price_changes", self.change, export_price_changes(s),
             "id",
             ident("id", "service_price_id", "service_id",
                   "staff_level_id", "old_amount", "new_amount",
                   "changed_by", "changed_at", "note"),
             ("service_external_id",),
             ("service_name", "staff_level_name")),
            ("refunds", self.refund, export_refunds(s, *WIDE), "id",
             ident("id", "sale_id", "amount", "reason", "tender",
                   "created_at"),
             (), ("refund_id", "salon_id")),
            ("breaks", self.brk, export_breaks(s, *YEAR_2026), "id",
             ident("id", "staff_member_id", "start", "end", "paid"),
             ("staff_member_external_id",), ("salon_id", "staff_name")),
            ("cashups", self.cashup, export_cashups(s, *YEAR_2026),
             "id",
             ident("id", "salon_id", "period_start", "period_end",
                   "total", "note", "created_at"),
             ("tender_totals",), ("cashup_id", "cash", "external")),
            ("receipts", self.receipt, export_receipts(salon=s), "id",
             ident("id", "sale_id", "salon_name", "total",
                   "recipient_email", "issued_at", "sent_at"),
             ("lines", "tender"),
             ("receipt_id", "salon_id", "client_id", "delivery_channel", "delivery_status")),
            ("reminder_sends", self.send, export_sends(s, *WIDE), "id",
             ident("id", "appointment_id", "client_id", "channel",
                   "status", "sent_at", "detail"),
             (), ("salon_id",)),
            ("campaigns", self.campaign, export_campaigns(s), "id",
             ident("id", "salon_id", "name", "channel", "subject",
                   "body", "status", "sent_at", "created_at",
                   "updated_at"), (), ()),
            ("campaign_sends", self.campaign_send,
             export_campaign_send_detail(s, *WIDE), "id",
             ident("id", "campaign_id", "client_id", "channel",
                   "status", "sent_at", "detail"),
             (), ("salon_id",)),
            ("staff_notifications", self.notification,
             export_staff_notifications(s), "id",
             ident("id", "staff_member_id", "appointment_id", "kind",
                   "created_at", "seen_at"),
             ("staff_member_external_id", "appointment_external_id"),
             ("salon_id", "staff_name")),
        ]

    def test_every_bundle_section_is_accounted_for(self):
        sections = set(self.data) - {"counts"}
        self.assertEqual(len(sections), 28)
        covered = {spec[0] for spec in self.specs()}
        self.assertEqual(sections, covered | NO_STANDALONE)
        for section in sections:
            self.assertEqual(
                self.data["counts"][section], len(self.data[section]))

    def test_bundle_matches_standalone_for_every_covered_section(self):
        for spec in self.specs():
            with self.subTest(section=spec[0]):
                self.check(*spec)

    def test_appointment_snapshot_and_price_book_payload_parity(self):
        # The standalone appointment row resolves service_name live
        # and keeps the stored snapshot under service_name_snapshot;
        # the bundle carries the snapshot as service_name. Both must
        # hold the same stored snapshot for this record.
        bundle = next(r for r in self.data["appointments"]
                      if r["id"] == self.appt.pk)
        standalone = export_appointments(self.salon, *YEAR_2026)[0]
        self.assertEqual(standalone["service_name_snapshot"],
                         bundle["service_name"])
        self.assertEqual(standalone["service_name"],
                         bundle["service_name"])

    def test_cashup_tender_totals_match_flattened_columns(self):
        # The bundle nests tender_totals; the standalone cashup
        # export flattens them to one column per tender slug. The
        # amounts must agree per slug for the same cashup.
        bundle = next(r for r in self.data["cashups"]
                      if r["id"] == self.cashup.pk)
        standalone = export_cashups(self.salon, *YEAR_2026)[0]
        for slug, total in bundle["tender_totals"].items():
            self.assertEqual(_norm(standalone[slug]), _norm(total))

    def test_bundle_never_carries_provider_reference(self):
        # Documented divergence, founding rule: the standalone
        # payment export carries provider_reference verbatim; the
        # bundle must not carry the key or the value, ever.
        standalone = export_payments(self.salon, *WIDE)[0]
        self.assertEqual(standalone["provider_reference"],
                         "PROV-SECRET-1")
        bundle = self.data["sale_payments"][0]
        self.assertNotIn("provider_reference", bundle)

    def test_no_standalone_set_is_empty(self):
        # campaign_sends was the last blind spot: it now has a
        # per-record standalone counterpart
        # (campaign_send_detail) and is wired into specs() above,
        # so no bundle section is excluded from parity checks.
        self.assertEqual(NO_STANDALONE, set())
