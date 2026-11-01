"""Export a salon's core data to a single JSON file.

Usage:
    python manage.py export_salon_data OUTPUT.json [--salon NAME]

Exit Principle (founding rule): anything a salon can enter, it can
fully export. This is part 1 of that test — the core records only:

- saloncore: Salon, ServiceCategory, Service, StaffLevel, ServicePrice
  (StaffLevel is included because ServicePrice rows reference it;
  without levels an exported price cannot be interpreted.)
- clients: Client (including the ``sms_opt_in`` / ``email_opt_in``
  flags) and ClientNote (persistent client record notes).
- team: StaffMember (including the ``online_bookable`` toggle).
- bookings: Appointment and AppointmentNote (appointment-only
  notes; a separate model from ClientNote — the two kinds never
  blur). Appointment rows carry their own ``external_id`` plus the
  ``client`` / ``staff_member`` / ``service`` references as both the
  internal ``*_id`` (following the other sections) and the related
  record's ``*_external_id`` where that model carries one.
- team: RosterPattern and ShiftOverride (the roster: recurring
  weekly patterns and one-date overrides, scoped through their
  staff member's salon). Both rows carry the staff reference as
  both the internal ``staff_member_id`` and the member's
  ``staff_member_external_id``, like appointments.
- checkout: Sale, SaleItem (sale lines) and Payment (sale payments),
  scoped through the sale's salon. Sale rows carry the client
  reference as both ``client_id`` and ``client_external_id``; line
  rows carry service/product references the same way. FOUNDING
  RULE: Payment's ``provider_reference`` is NEVER exported — it is
  a payment-provider identifier and provider-agnostic core carries
  no provider identifiers, SDK fields, or provider names.
- catalog: Product (retail products, scoped by salon like clients
  and staff). Stock is NOT exported as a field: it is derived from
  StockMovement rows, never stored on Product, so there is no
  stock field to emit — money fields (``price``, ``cost_price``)
  are emitted exactly as stored, as strings.
- catalog: StockMovement (the stock event log, scoped through
  its product's salon). Rows carry the product reference as both
  the internal ``product_id`` and the product's
  ``product_external_id``, like sale lines. ``quantity_delta`` is
  emitted as the exact stored integer, never a float.
- team: AttendanceRecord (the time-clock event log, scoped
  through its staff member's salon). Rows carry the staff
  reference as both the internal ``staff_member_id`` and the
  member's ``staff_member_external_id``, like roster rows;
  ``recorded_at`` is emitted as ISO-8601 with its timezone.
- saloncore: PriceChange (the append-only price audit trail,
  scoped through its service price's service -> category ->
  salon chain). Rows carry the price reference as the internal
  ``service_price_id`` plus the price's ``service_id`` /
  ``service_external_id`` and ``staff_level_id`` so a restore
  can re-anchor the change on the restored price; ``old_amount``
  / ``new_amount`` are emitted as exact strings (money never
  floats; ``old_amount`` is ``None`` when the change has none)
  and ``changed_at`` as ISO-8601 with its timezone.
- checkout: Refund (the append-only record of money returned
  against a sale, scoped through its sale's salon). Rows carry
  the sale reference as the internal ``sale_id``, like sale
  items and payments; ``amount`` is emitted as an exact string
  (money never floats), ``tender`` is a core ``Payment.Method``
  slug (no provider concept), and ``created_at`` as ISO-8601
  with its timezone.
- bookings: Break (a stylist's blocked-off time, scoped through
  its staff member's salon). Rows carry the staff reference as
  both the internal ``staff_member_id`` and the member's
  ``staff_member_external_id``, like attendance records;
  ``start`` / ``end`` are emitted as ISO-8601 with timezone
  via ``_dt`` and ``paid`` as a real boolean.
- checkout: Cashup (a close-out snapshot of a period's takings,
  scoped directly by its salon). Rows carry the salon reference
  as the internal ``salon_id``; ``period_start`` /
  ``period_end`` / ``created_at`` as ISO-8601 with timezone,
  ``tender_totals`` verbatim (method slug -> total as string),
  and ``total`` as an exact string (money never floats).
- checkout: Receipt (an immutable snapshot of a sale, scoped
  through its sale's salon). Rows carry the sale reference as
  the internal ``sale_id``, like refunds; ``lines`` / ``tender``
  verbatim (money inside them stored as strings), ``total`` as
  an exact string (money never floats), and ``issued_at`` /
  ``sent_at`` as ISO-8601 with timezone via ``_dt``
  (``sent_at`` is ``None`` when unsent).
- messaging: ReminderSend (the log of dispatched appointment
  reminders, scoped through its appointment — appointments are
  themselves scoped through their client's salon). Rows carry
  the appointment and client references as the internal
  ``appointment_id`` / ``client_id``, like refunds carry their
  ``sale_id``; ``detail`` is free-form send detail exported
  verbatim, and ``sent_at`` as ISO-8601 with timezone via
  ``_dt``.

The ``payload`` (whole source record, stored verbatim) is emitted
for every section whose model carries one — clients, services,
appointments and products — so a salon_data restore preserves it
exactly. StaffMember carries no ``payload`` field, so its section
emits none.

No new models and no provider concepts: plain querysets turned into
plain dicts, Decimals as strings and datetimes as ISO-8601 so the file
round-trips losslessly through ``json.load``. Without ``--salon`` every
salon in the database is exported; with it, only that salon's records
(clients/staff scoped by salon, categories/services/prices/levels
scoped through their salon/category/service chain).
"""

import json

from django.core.management.base import BaseCommand, CommandError

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


def _dt(value):
    return value.isoformat() if value is not None else None


class Command(BaseCommand):
    help = "Export salon core data (price book, clients, staff, appointments, products, sales, stock movements, attendance, price changes, refunds, breaks, cashups, receipts, reminder sends) to one JSON file."

    def add_arguments(self, parser):
        parser.add_argument("output", help="Path of the JSON file to write.")
        parser.add_argument(
            "--salon", default=None,
            help="Only export the salon with this exact name.",
        )

    def handle(self, *args, **options):
        salons = Salon.objects.all()
        if options["salon"]:
            salons = salons.filter(name=options["salon"])
            if not salons.exists():
                raise CommandError(f"No salon named {options['salon']!r}.")
        salon_ids = list(salons.values_list("id", flat=True))

        categories = ServiceCategory.objects.filter(salon_id__in=salon_ids)
        category_ids = list(categories.values_list("id", flat=True))
        services = Service.objects.filter(category_id__in=category_ids)
        service_ids = list(services.values_list("id", flat=True))
        levels = StaffLevel.objects.filter(salon_id__in=salon_ids)
        prices = ServicePrice.objects.filter(service_id__in=service_ids)
        price_ids = list(prices.values_list("id", flat=True))
        price_changes = PriceChange.objects.filter(
            service_price_id__in=price_ids).select_related(
                "service_price", "service_price__service").order_by(
                    "changed_at", "id")
        clients = Client.objects.filter(salon_id__in=salon_ids)
        client_ids = list(clients.values_list("id", flat=True))
        notes = ClientNote.objects.filter(client_id__in=client_ids)
        staff = StaffMember.objects.filter(salon_id__in=salon_ids)
        staff_ids = list(staff.values_list("id", flat=True))
        roster_patterns = RosterPattern.objects.filter(
            staff_member_id__in=staff_ids
        ).select_related("staff_member")
        shift_overrides = ShiftOverride.objects.filter(
            staff_member_id__in=staff_ids
        ).select_related("staff_member")
        appointments = Appointment.objects.filter(
            client_id__in=client_ids
        ).select_related("client", "staff_member", "service")
        appointment_ids = list(appointments.values_list("id", flat=True))
        appointment_notes = AppointmentNote.objects.filter(
            appointment_id__in=appointment_ids
        )
        products = Product.objects.filter(salon_id__in=salon_ids)
        product_ids = list(products.values_list("id", flat=True))
        stock_movements = StockMovement.objects.filter(
            product_id__in=product_ids).select_related("product")
        sales = Sale.objects.filter(
            salon_id__in=salon_ids).select_related("client")
        sale_ids = list(sales.values_list("id", flat=True))
        sale_items = SaleItem.objects.filter(
            sale_id__in=sale_ids).select_related("service", "product")
        sale_payments = Payment.objects.filter(sale_id__in=sale_ids)
        refunds = Refund.objects.filter(sale_id__in=sale_ids)
        attendance_records = AttendanceRecord.objects.filter(
            staff_member_id__in=staff_ids).select_related("staff_member")
        breaks = Break.objects.filter(
            staff_member_id__in=staff_ids).select_related("staff_member")
        cashups = Cashup.objects.filter(salon_id__in=salon_ids)
        receipts = Receipt.objects.filter(sale__salon_id__in=salon_ids)
        reminder_sends = ReminderSend.objects.filter(
            appointment_id__in=appointment_ids)

        data = {
            "salons": [
                {
                    "id": s.id, "name": s.name, "timezone": s.timezone,
                    "currency": s.currency, "tagline": s.tagline,
                    "logo_url": s.logo_url,
                    "primary_color": s.primary_color,
                    "accent_color": s.accent_color,
                    "created_at": _dt(s.created_at),
                    "updated_at": _dt(s.updated_at),
                }
                for s in salons
            ],
            "service_categories": [
                {
                    "id": c.id, "salon_id": c.salon_id, "name": c.name,
                    "sort_order": c.sort_order, "active": c.active,
                }
                for c in categories
            ],
            "services": [
                {
                    "id": s.id, "category_id": s.category_id,
                    "external_id": s.external_id, "name": s.name,
                    "description": s.description,
                    "service_minutes": s.service_minutes,
                    "processing_minutes": s.processing_minutes,
                    "finishing_minutes": s.finishing_minutes,
                    "active": s.active, "payload": s.payload,
                }
                for s in services
            ],
            "staff_levels": [
                {
                    "id": lvl.id, "salon_id": lvl.salon_id, "name": lvl.name,
                    "sort_order": lvl.sort_order, "active": lvl.active,
                }
                for lvl in levels
            ],
            "service_prices": [
                {
                    "id": p.id, "service_id": p.service_id,
                    "staff_level_id": p.staff_level_id,
                    "amount": str(p.amount), "is_from": p.is_from,
                    "active": p.active,
                }
                for p in prices
            ],
            "clients": [
                {
                    "id": c.id, "salon_id": c.salon_id,
                    "external_id": c.external_id,
                    "first_name": c.first_name, "last_name": c.last_name,
                    "email": c.email, "phone": c.phone,
                    "sms_opt_in": c.sms_opt_in,
                    "email_opt_in": c.email_opt_in,
                    "active": c.active, "created_at": _dt(c.created_at),
                    "payload": c.payload,
                }
                for c in clients
            ],
            "client_notes": [
                {
                    "id": n.id, "client_id": n.client_id, "body": n.body,
                    "author_name": n.author_name,
                    "created_at": _dt(n.created_at),
                }
                for n in notes
            ],
            "staff_members": [
                {
                    "id": m.id, "salon_id": m.salon_id,
                    "external_id": m.external_id,
                    "display_name": m.display_name,
                    "staff_level_id": m.staff_level_id,
                    "online_bookable": m.online_bookable,
                    "active": m.active,
                }
                for m in staff
            ],
            "roster_patterns": [
                {
                    "id": r.id,
                    "staff_member_id": r.staff_member_id,
                    "staff_member_external_id": r.staff_member.external_id,
                    "weekday": r.weekday,
                    "start_time": _dt(r.start_time),
                    "end_time": _dt(r.end_time),
                    "active": r.active,
                }
                for r in roster_patterns
            ],
            "shift_overrides": [
                {
                    "id": o.id,
                    "staff_member_id": o.staff_member_id,
                    "staff_member_external_id": o.staff_member.external_id,
                    "date": _dt(o.date),
                    "is_off": o.is_off,
                    "start_time": _dt(o.start_time),
                    "end_time": _dt(o.end_time),
                }
                for o in shift_overrides
            ],
            "appointments": [
                {
                    "id": a.id,
                    "external_id": a.external_id,
                    "client_id": a.client_id,
                    "client_external_id": a.client.external_id,
                    "staff_member_id": a.staff_member_id,
                    "staff_member_external_id": a.staff_member.external_id,
                    "service_id": a.service_id,
                    "service_external_id": (
                        a.service.external_id if a.service else None
                    ),
                    "service_name": a.service_name,
                    "start": _dt(a.start), "end": _dt(a.end),
                    "status": a.status, "origin": a.origin,
                    "price_override": (
                        str(a.price_override)
                        if a.price_override is not None else None
                    ),
                    "created_at": _dt(a.created_at),
                    "updated_at": _dt(a.updated_at),
                    "payload": a.payload,
                }
                for a in appointments
            ],
            "appointment_notes": [
                {
                    "id": n.id, "appointment_id": n.appointment_id,
                    "body": n.body, "author_name": n.author_name,
                    "created_at": _dt(n.created_at),
                }
                for n in appointment_notes
            ],
            "products": [
                {
                    "id": p.id, "salon_id": p.salon_id,
                    "external_id": p.external_id, "name": p.name,
                    "sku": p.sku, "barcode": p.barcode,
                    "price": str(p.price),
                    "cost_price": (
                        str(p.cost_price)
                        if p.cost_price is not None else None
                    ),
                    "active": p.active,
                    "brand_name": p.brand_name,
                    "category_name": p.category_name,
                    "product_type": p.product_type,
                    "payload": p.payload,
                }
                for p in products
            ],
            "sales": [
                {
                    "id": s.id, "salon_id": s.salon_id,
                    "client_id": s.client_id,
                    "client_external_id": (
                        s.client.external_id if s.client else None),
                    "status": s.status,
                    "created_at": _dt(s.created_at),
                    "completed_at": _dt(s.completed_at),
                    "voided_at": _dt(s.voided_at),
                    "void_reason": s.void_reason,
                }
                for s in sales
            ],
            "sale_items": [
                {
                    "id": i.id, "sale_id": i.sale_id, "kind": i.kind,
                    "service_id": i.service_id,
                    "service_external_id": (
                        i.service.external_id if i.service else None),
                    "product_id": i.product_id,
                    "product_external_id": (
                        i.product.external_id if i.product else None),
                    "description": i.description,
                    "quantity": i.quantity,
                    "unit_price": str(i.unit_price),
                }
                for i in sale_items
            ],
            "sale_payments": [
                {
                    # provider_reference deliberately omitted:
                    # provider-agnostic core exports no provider ids.
                    "id": pay.id, "sale_id": pay.sale_id,
                    "method": pay.method, "amount": str(pay.amount),
                    "status": pay.status,
                    "created_at": _dt(pay.created_at),
                    "updated_at": _dt(pay.updated_at),
                }
                for pay in sale_payments
            ],
            "attendance_records": [
                {
                    "id": r.id,
                    "staff_member_id": r.staff_member_id,
                    "staff_member_external_id": r.staff_member.external_id,
                    "event_type": r.event_type,
                    "recorded_at": _dt(r.recorded_at),
                    "note": r.note,
                }
                for r in attendance_records
            ],
            "stock_movements": [
                {
                    "id": m.id, "product_id": m.product_id,
                    "product_external_id": m.product.external_id,
                    "kind": m.kind,
                    "quantity_delta": m.quantity_delta,
                    "note": m.note,
                    "created_at": _dt(m.created_at),
                }
                for m in stock_movements
            ],
            "price_changes": [
                {
                    "id": c.id,
                    "service_price_id": c.service_price_id,
                    "service_id": c.service_price.service_id,
                    "service_external_id": (
                        c.service_price.service.external_id),
                    "staff_level_id": c.service_price.staff_level_id,
                    "old_amount": (
                        str(c.old_amount)
                        if c.old_amount is not None else None
                    ),
                    "new_amount": str(c.new_amount),
                    "changed_by": c.changed_by,
                    "changed_at": _dt(c.changed_at),
                    "note": c.note,
                }
                for c in price_changes
            ],
            "refunds": [
                {
                    "id": r.id, "sale_id": r.sale_id,
                    "amount": str(r.amount), "reason": r.reason,
                    "tender": r.tender,
                    "created_at": _dt(r.created_at),
                }
                for r in refunds
            ],
            "breaks": [
                {
                    "id": b.id,
                    "staff_member_id": b.staff_member_id,
                    "staff_member_external_id": b.staff_member.external_id,
                    "start": _dt(b.start), "end": _dt(b.end),
                    "paid": b.paid,
                }
                for b in breaks
            ],
            "cashups": [
                {
                    "id": c.id, "salon_id": c.salon_id,
                    "period_start": _dt(c.period_start),
                    "period_end": _dt(c.period_end),
                    "tender_totals": c.tender_totals,
                    "total": str(c.total), "note": c.note,
                    "created_at": _dt(c.created_at),
                }
                for c in cashups
            ],
            "receipts": [
                {
                    "id": r.id, "sale_id": r.sale_id,
                    "salon_name": r.salon_name, "lines": r.lines,
                    "total": str(r.total), "tender": r.tender,
                    "recipient_email": r.recipient_email,
                    "issued_at": _dt(r.issued_at),
                    "sent_at": _dt(r.sent_at),
                }
                for r in receipts
            ],
            "reminder_sends": [
                {
                    "id": r.id, "appointment_id": r.appointment_id,
                    "client_id": r.client_id, "channel": r.channel,
                    "status": r.status, "sent_at": _dt(r.sent_at),
                    "detail": r.detail,
                }
                for r in reminder_sends
            ],
        }
        data["counts"] = {
            key: len(value) for key, value in data.items()
        }

        try:
            with open(options["output"], "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=False)
                fh.write("\n")
        except OSError as exc:
            raise CommandError(
                f"Cannot write export file {options['output']}: {exc}"
            ) from exc

        summary = ", ".join(
            f"{key}={count}" for key, count in data["counts"].items()
        )
        self.stdout.write(f"EXPORT_SUMMARY {summary}")
        self.stdout.write(f"Wrote {options['output']}")
