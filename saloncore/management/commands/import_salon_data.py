"""Import salon core data from an export_salon_data JSON file.

Usage:
    python manage.py import_salon_data INPUT.json

This is the restore side of the Exit Test: it consumes exactly the
JSON format written by ``export_salon_data`` (see that command for the
section list) and restores Salon, ServiceCategory, Service,
StaffLevel, ServicePrice, Client, ClientNote, StaffMember,
Appointment, AppointmentNote, Product, RosterPattern,
ShiftOverride, Sale, SaleItem, Payment, StockMovement,
AttendanceRecord, PriceChange, Refund, Break and Cashup records. The ``products``,
``roster_patterns``, ``shift_overrides``, ``sales``, ``sale_items``,
``sale_payments``, ``stock_movements``, ``attendance_records``,
``price_changes``, ``refunds``, ``breaks`` and ``cashups`` sections are optional on read: an export
file written before they existed (no such section, no ``counts``
entry for it) imports exactly as before, with the section
treated as empty. Roster rows restore idempotently too:
RosterPattern keyed by (staff_member, weekday, start_time,
end_time) — the model allows multiple patterns per weekday —
and ShiftOverride by (staff_member, date), its unique
constraint; both resolve their staff member by ``external_id``
when present, else by the file-local id map, like appointments.

The exporter's ``id`` values are file-local: foreign keys in the
file refer to those ids, so the import builds old-id -> new-record
maps section by section (salons, then categories/levels, then
services, prices, clients, notes, staff) and never writes the file's
ids into the database.

Idempotent: every record is written with ``update_or_create`` keyed
by its natural identity, so re-running an import updates in place
and creates nothing twice:

- Salon            <- name
- ServiceCategory  <- (salon, name)
- StaffLevel       <- (salon, name)
- Service          <- external_id when present, else (category, name)
- ServicePrice     <- (service, staff_level) — the model's own
  unique constraint
- Client           <- (salon, external_id) when present, else
  (salon, first_name, last_name, email, phone)
- ClientNote       <- (client, body, author_name)
- StaffMember      <- (salon, external_id) when present, else
  (salon, display_name)
- Appointment      <- external_id when present, else
  (client, staff_member, start, end). Its client / staff_member /
  service links resolve by the related record's ``*_external_id``
  first, falling back to the file-local ``*_id`` map (the same maps
  the other sections use); a link that resolves by neither fails
  closed in phase 1 — no link is ever fabricated.
- AppointmentNote  <- (appointment, body, author_name), attached to
  the restored appointment its ``appointment_id`` names.
- Product          <- external_id when present, else
  (salon, name, sku, barcode). Stock is never imported: it is
  derived from StockMovement rows, not stored on Product.
- Sale             <- (salon, client, created_at, completed_at,
  voided_at); restored after products so sale lines can resolve
  them. SaleItem <- (sale, kind, service, product, description);
  Payment (sale_payments) <- (sale, method, created_at).
- StockMovement    <- (product, kind, quantity_delta, note,
  created_at) when ``created_at`` is present, else (product,
  kind, quantity_delta, note). The model has no unique
  constraint and no external_id of its own; created_at is the
  anchor that distinguishes two otherwise identical movements,
  exactly as for Sale/Payment. Its product link resolves by
  ``product_external_id`` first, falling back to the file-local
  ``product_id`` map; a link that resolves by neither fails
  closed in phase 1.
- AttendanceRecord <- (staff_member, recorded_at, event_type).
  The model has no external_id of its own and no unique
  constraint; ``recorded_at`` is the anchor that distinguishes
  two otherwise identical events, exactly as ``created_at``
  anchors Sale/Payment/StockMovement, and ``event_type`` keeps a
  check-in and a check-out recorded at the same instant distinct.
  ``note`` is a default (updated in place on re-import). Its
  staff link resolves by ``staff_member_external_id`` first,
  falling back to the file-local ``staff_member_id`` map; a link
  that resolves by neither fails closed in phase 1.
  ``recorded_at`` must be timezone-explicit (TF-7): it is the
  identity anchor, so unlike a best-effort ``created_at`` it is
  required, and a naive value is rejected in phase 1, never
  guessed into a zone.
- PriceChange    <- (service_price, changed_at, old_amount,
  new_amount, changed_by, note). PriceChange is an append-only
  audit trail, so restore never updates an existing row: the
  natural key above is looked up with ``get_or_create``
  semantics — a change already restored is returned untouched
  and a re-import never duplicates history. Its price link
  resolves by the price's service ``service_external_id`` plus
  ``staff_level_id`` (the price's own identity) first, falling
  back to the file-local ``service_price_id`` map; a link that
  resolves by neither fails closed in phase 1. ``changed_at``
  must be timezone-explicit (TF-7) for the same reason as
  ``recorded_at``: it is the identity anchor, required, and a
  naive value is rejected in phase 1. Amounts are exact
  strings, parsed as Decimal, never floats. Restoring the
  historical ``changed_at`` on a newly created row is the one
  write past the model's append-only guard: creation stamps
  ``auto_now_add``, so the importer re-stamps the exported
  instant once, at creation only, through a plain queryset
  update (``PriceChangeQuerySet.update`` blocks updates by
  design, and no existing row is ever re-stamped).
  FOUNDING RULE: Payment's ``provider_reference`` is never
  imported or exported — it is a payment-provider identifier and
  provider-agnostic core carries none; if a file carries it, it
  is an unknown key and TF-11 names it as dropped
  (``sale_payments.provider_reference``).
- Refund         <- (sale, amount, reason, tender, created_at).
  Refund is an append-only record of money returned, so restore
  never updates an existing row: the natural key above is
  looked up with ``get_or_create`` semantics — a refund
  already restored is returned untouched and a re-import never
  duplicates it. Its sale link resolves by the file-local
  ``sale_id`` map, like sale items and payments (Sale carries
  no external_id); a link that resolves by neither fails
  closed in phase 1. ``created_at`` must be
  timezone-explicit (TF-7) for the same reason as
  ``changed_at`` / ``recorded_at``: it is the identity anchor,
  required, and a naive value is rejected in phase 1.
  ``amount`` is an exact string, parsed as Decimal, never a
  float, and ``tender`` is a core ``Payment.Method`` slug —
  no provider concept. Restoring the historical
  ``created_at`` on a newly created row follows the
  price_changes pattern: creation stamps ``auto_now_add``, so
  the importer re-stamps the exported instant once, at
  creation only, and no existing row is ever re-stamped.
- Break          <- (staff_member, start, end). Restore uses
  ``get_or_create`` with ``paid`` as a default — a break
  already restored is returned untouched and a re-import
  never duplicates it. Its staff link resolves by
  ``staff_member_external_id`` first, falling back to the
  file-local ``staff_member_id`` map, like attendance; a
  link that resolves by neither fails closed in phase 1.
  ``start`` / ``end`` must be timezone-explicit (TF-7):
  they are the identity anchor, required, and a naive
  value is rejected in phase 1. ``paid`` is STRICT-parsed
  (TF-3): missing / null / non-bool is a named
  CommandError, never guessed.
- Cashup         <- (salon, period_start, period_end,
  created_at). A cashup is a snapshot, so restore never updates
  an existing row: the natural key above is looked up with
  ``get_or_create`` semantics — a cashup already restored is
  returned untouched and a re-import never duplicates it;
  ``tender_totals``, ``total`` and ``note`` are creation
  defaults only. Its salon link resolves by the file-local
  ``salon_id`` map; a link that resolves by neither fails
  closed in phase 1. ``period_start``, ``period_end`` and
  ``created_at`` must be timezone-explicit (TF-7): they are
  identity anchors, required, and naive values are rejected
  in phase 1. ``total`` is an exact string, parsed as Decimal,
  never a float, and ``tender_totals`` must be a dict of
  Decimal-parseable string values keyed by core
  ``Payment.Method`` slugs — no provider concept. Restoring
  ``created_at`` follows the refunds pattern: re-stamped once
  at creation only, never on an existing row.

No provider concepts: external ids are the generic fields the models
already carry.

Two-phase, validate-before-write (N-M19): phase 1 validates the
ENTIRE file — every reference resolves to an id present in the file,
every required field is present, every price amount parses — before
phase 2 writes a single row. A bad file (bad JSON, missing sections,
missing fields, dangling references anywhere including the last
section, counts that disagree with the sections) raises
``CommandError`` and changes nothing on ANY backend. This must not
rely on ``transaction.atomic`` rollback: on NEDB ``atomic()`` rolls
back nothing (DYOR §9.4; strictness probe §4 signature 8), so the
atomicity guarantee lives in this command layer (probe §5). The
``atomic`` decorator is kept only as defence-in-depth on backends
that do support transactions.

Strict boolean types (TF-3): the boolean fields the exporter always
carries — ``active`` (service_categories, services, staff_levels,
service_prices, clients, staff_members, products), ``is_from``
(service_prices) and ``online_bookable`` (staff_members) — are
validated in phase 1 and never guessed in phase 2. The three bad
shapes are distinct, named errors: a missing key is not a value, an
explicit ``null`` is rejected because none of these model fields can
hold null, and any non-boolean value (the string ``"false"``, the
number ``1``) is rejected rather than coerced — under plain Python
truthiness ``"false"`` would silently restore as ``True``. A file
that passes phase 1 therefore carries a real JSON boolean for every
one of these fields, and phase 2 restores exactly that value.

Timezone-explicit datetimes (TF-7): every datetime this command
restores — ``created_at`` on salons, clients, client notes,
appointments and appointment notes, plus appointment ``start`` /
``end`` — must carry an explicit timezone offset. A naive value
(e.g. ``2026-01-01T10:00:00`` with no offset) is rejected in
phase 1 with a named ``CommandError`` and zero writes, never
stored as-if-UTC under ``USE_TZ`` and never silently made aware:
this command's restore contract is fail-closed validation
(TF-3 precedent), so an ambiguous wall time fails the whole file
rather than being guessed into the salon's timezone. An absent
``created_at`` (missing / ``null`` / empty) is distinct from a
naive one — there is simply no timestamp to restore, so it stays
a best-effort skip; a present but unparseable ``created_at`` is
likewise a phase-1 ``CommandError``, never a silent drop.

Faithful external ids (TF-6): every id this command consumes —
file-local ``id`` values, every ``*_id`` reference (including
``category_id``), the ``external_id`` of the clients, staff_members,
services, appointments and products sections, and appointments'
and stock_movements' ``*_external_id`` link fields — is normalised to ``str`` in phase 1,
so a numeric id and its string spelling (``123`` vs ``"123"``) are
the same identity in every lookup, map and ``update_or_create`` key.
An ``external_id`` / ``*_external_id`` longer than its model field's
``max_length`` is never silently truncated (a shortened id would
become a different identity, and two overlong ids sharing a prefix
would collide into one): it raises ``CommandError`` in phase 1
naming the section and record, so the whole file writes zero rows.

Payloads (verbatim retention): the ``payload`` field carried by
``Service`` / ``Client`` / ``Appointment`` / ``Product`` is a known
key in those four sections and is restored verbatim when present —
stored exactly as exported, never transformed. Sections whose models
carry no payload (Salon, ServiceCategory, StaffLevel,
ServicePrice, the notes and StaffMember — StaffMember has no
``payload`` field) emit and consume none. An older export file
without ``payload`` keys imports exactly as before: new records
land with the model's empty default and nothing errors.

Unknown sections / keys (TF-11): anything in the file this command
does not consume — an unknown top-level section, or an unknown key
inside a record of a known section (or inside ``counts``) — has no
model home in the salon_data shape. Such data is therefore never
dropped silently: every unknown section and key is listed BY NAME
in an ``IMPORT_DROPPED`` line in the import summary output (an
explicit ``none`` when there is nothing dropped), while all known
data imports exactly as before.

Dry run (TF-12): with ``--dry-run`` the file is loaded and
validated in phase 1 exactly as for a real import, then a JSON
report from ``saloncore.dry_run`` is printed to stdout — one
report per section, over that section's rows, with that section's
``KNOWN_KEYS`` as the mapped keys (so its ``unmapped_keys`` name
exactly the keys TF-11 would list as dropped for that section,
keeping null / missing / empty-string counts distinct) — and the
command returns before phase 2 writes a single row.
"""

import json
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.query import QuerySet as PlainQuerySet
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.utils.timezone import is_naive

from bookings.models import Appointment, AppointmentNote, Break
from checkout.models import Cashup, Payment, Refund, Sale, SaleItem
from catalog.models import Product, StockMovement
from clients.models import Client, ClientNote
from saloncore.dry_run import build_dry_run_reports
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

SECTIONS = (
    "salons", "service_categories", "services", "staff_levels",
    "service_prices", "clients", "client_notes", "staff_members",
    "appointments", "appointment_notes", "products",
    "roster_patterns", "shift_overrides",
    "sales", "sale_items", "sale_payments", "stock_movements",
    "attendance_records", "price_changes", "refunds", "breaks", "cashups",
)

# Sections an older export file may legitimately lack entirely:
# missing means empty, never an error (back-compat).
OPTIONAL_SECTIONS = ("products", "roster_patterns", "shift_overrides",
                     "sales", "sale_items", "sale_payments",
                     "stock_movements", "attendance_records",
                     "price_changes", "refunds", "breaks", "cashups")

# Every key the exporter emits (hence the importer may consume) per
# section. Any other key in a record is unknown (TF-11).
KNOWN_KEYS = {
    "salons": {"id", "name", "timezone", "currency", "created_at",
               "updated_at"},
    "service_categories": {"id", "salon_id", "name", "sort_order",
                           "active"},
    "services": {"id", "category_id", "external_id", "name",
                 "description", "service_minutes",
                 "processing_minutes", "finishing_minutes", "active",
                 "payload"},
    "staff_levels": {"id", "salon_id", "name", "sort_order", "active"},
    "service_prices": {"id", "service_id", "staff_level_id", "amount",
                       "is_from", "active"},
    "clients": {"id", "salon_id", "external_id", "first_name",
                "last_name", "email", "phone", "sms_opt_in",
                "email_opt_in", "active", "created_at", "payload"},
    "client_notes": {"id", "client_id", "body", "author_name",
                     "created_at"},
    "staff_members": {"id", "salon_id", "external_id", "display_name",
                      "staff_level_id", "online_bookable", "active"},
    "appointments": {"id", "external_id", "client_id",
                     "client_external_id", "staff_member_id",
                     "staff_member_external_id", "service_id",
                     "service_external_id", "service_name", "start",
                     "end", "status", "origin", "price_override",
                     "created_at", "updated_at", "payload"},
    "appointment_notes": {"id", "appointment_id", "body",
                          "author_name", "created_at"},
    "products": {"id", "salon_id", "external_id", "name", "sku",
                 "barcode", "price", "cost_price", "active",
                 "brand_name", "category_name", "product_type",
                 "payload"},
    "roster_patterns": {"id", "staff_member_id",
                        "staff_member_external_id", "weekday",
                        "start_time", "end_time", "active"},
    "shift_overrides": {"id", "staff_member_id",
                        "staff_member_external_id", "date", "is_off",
                        "start_time", "end_time"},
    "sales": {"id", "salon_id", "client_id", "client_external_id",
              "status", "created_at", "completed_at", "voided_at",
              "void_reason"},
    "sale_items": {"id", "sale_id", "kind", "service_id",
                   "service_external_id", "product_id",
                   "product_external_id", "description", "quantity",
                   "unit_price"},
    "sale_payments": {"id", "sale_id", "method", "amount", "status",
                      "created_at", "updated_at"},
    "stock_movements": {"id", "product_id", "product_external_id",
                        "kind", "quantity_delta", "note",
                        "created_at"},
    "attendance_records": {"id", "staff_member_id",
                           "staff_member_external_id", "event_type",
                           "recorded_at", "note"},
    "price_changes": {"id", "service_price_id", "service_id",
                      "service_external_id", "staff_level_id",
                      "old_amount", "new_amount", "changed_by",
                      "changed_at", "note"},
    "refunds": {"id", "sale_id", "amount", "reason", "tender",
                "created_at"},
    "breaks": {"id", "staff_member_id",
               "staff_member_external_id", "start", "end", "paid"},
    "cashups": {"id", "salon_id", "period_start", "period_end",
                "tender_totals", "total", "note", "created_at"},
}

TOP_LEVEL_KEYS = set(SECTIONS) | {"counts"}


def _unknown_drops(data):
    """Return (unknown_sections, unknown_keys) present in ``data``.

    ``unknown_sections``: sorted top-level keys that are neither a
    known section nor ``counts``. ``unknown_keys``: sorted unique
    ``section.key`` names for keys outside KNOWN_KEYS in known
    sections, plus ``counts.<key>`` for counts entries naming no
    known section. Pure inspection — writes nothing.
    """
    unknown_sections = sorted(set(data) - TOP_LEVEL_KEYS)
    unknown_keys = set()
    counts = data.get("counts")
    if isinstance(counts, dict):
        for key in counts:
            if key not in SECTIONS:
                unknown_keys.add(f"counts.{key}")
    for section in SECTIONS:
        rows = data.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                for key in row:
                    if key not in KNOWN_KEYS[section]:
                        unknown_keys.add(f"{section}.{key}")
    return unknown_sections, sorted(unknown_keys)


def _load(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except OSError as exc:
        raise CommandError(f"Cannot read import file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"Import file {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CommandError("Import file must contain a JSON object.")
    for section in SECTIONS:
        if section in OPTIONAL_SECTIONS and section not in data:
            # Back-compat: a pre-products export has no section at
            # all; it imports exactly as before, as an empty one.
            data[section] = []
        if not isinstance(data.get(section), list):
            raise CommandError(f"Import file is missing section {section!r}.")
    counts = data.get("counts")
    if counts is not None:
        for section in SECTIONS:
            if section in OPTIONAL_SECTIONS and section not in counts:
                continue
            if counts.get(section) != len(data[section]):
                raise CommandError(
                    f"counts[{section!r}]={counts.get(section)} disagrees "
                    f"with the section's {len(data[section])} records."
                )
    return data


def _require(row, section, fields):
    if not isinstance(row, dict):
        raise CommandError(f"Record in section {section!r} is not an object.")
    for field in fields:
        if field not in row:
            raise CommandError(
                f"Record in section {section!r} is missing {field!r}.")


BOOL_FIELDS = {
    "service_categories": ("active",),
    "services": ("active",),
    "staff_levels": ("active",),
    "service_prices": ("is_from", "active"),
    "clients": ("active",),
    "staff_members": ("online_bookable", "active"),
    "products": ("active",),
    "roster_patterns": ("active",),
    "shift_overrides": ("is_off",),
    "breaks": ("paid",),
}


def _check_bool(row, section, field):
    """Phase-1 strict check for one boolean field (TF-3).

    Missing, explicit null and non-boolean values are three
    different problems and get three different messages; none of
    them is ever repaired by guessing a default.
    """
    label = f"section {section!r} record id {row.get('id')!r}"
    if field not in row:
        raise CommandError(
            f"Missing boolean field: {label} has no {field!r}; "
            f"export files always carry it and it is never guessed.")
    value = row[field]
    if value is None:
        raise CommandError(
            f"Null boolean field: {label} has {field!r}=null, but "
            f"the model field cannot hold null.")
    if not isinstance(value, bool):
        raise CommandError(
            f"Bad boolean field: {label} has {field!r}={value!r} "
            f"({type(value).__name__}), not a JSON boolean.")


def _norm_id(value):
    """Normalise an id scalar to its string spelling (TF-6).

    Ints and strings become ``str(value)`` (strings stripped, like
    the other TF-6 importers); anything else (None, bool, containers,
    floats) is returned unchanged so existing validation treats it
    exactly as before.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


# Id-bearing fields per section, normalised in phase 1 (TF-6).
_ID_FIELDS = {
    "salons": ("id",),
    "service_categories": ("id", "salon_id"),
    "services": ("id", "category_id", "external_id"),
    "staff_levels": ("id", "salon_id"),
    "service_prices": ("id", "service_id", "staff_level_id"),
    "clients": ("id", "salon_id", "external_id"),
    "client_notes": ("id", "client_id"),
    "staff_members": ("id", "salon_id", "staff_level_id",
                      "external_id"),
    "appointments": ("id", "external_id", "client_id",
                     "client_external_id", "staff_member_id",
                     "staff_member_external_id", "service_id",
                     "service_external_id"),
    "appointment_notes": ("id", "appointment_id"),
    "products": ("id", "salon_id", "external_id"),
    "roster_patterns": ("id", "staff_member_id",
                        "staff_member_external_id"),
    "shift_overrides": ("id", "staff_member_id",
                        "staff_member_external_id"),
    "sales": ("id", "salon_id", "client_id", "client_external_id"),
    "sale_items": ("id", "sale_id", "service_id",
                   "service_external_id", "product_id",
                   "product_external_id"),
    "sale_payments": ("id", "sale_id"),
    "stock_movements": ("id", "product_id", "product_external_id"),
    "attendance_records": ("id", "staff_member_id",
                           "staff_member_external_id"),
    "price_changes": ("id", "service_price_id", "service_id",
                      "service_external_id", "staff_level_id"),
    "refunds": ("id", "sale_id"),
    "breaks": ("id", "staff_member_id",
               "staff_member_external_id"),
    "cashups": ("id", "salon_id"),
}

# (section, field) -> model whose external_id limit governs it.
_EXTERNAL_ID_LIMITS = {
    ("services", "external_id"):
        Service._meta.get_field("external_id").max_length,
    ("clients", "external_id"):
        Client._meta.get_field("external_id").max_length,
    ("staff_members", "external_id"):
        StaffMember._meta.get_field("external_id").max_length,
    ("appointments", "external_id"):
        Appointment._meta.get_field("external_id").max_length,
    ("appointments", "client_external_id"):
        Client._meta.get_field("external_id").max_length,
    ("appointments", "staff_member_external_id"):
        StaffMember._meta.get_field("external_id").max_length,
    ("appointments", "service_external_id"):
        Service._meta.get_field("external_id").max_length,
    ("products", "external_id"):
        Product._meta.get_field("external_id").max_length,
    ("roster_patterns", "staff_member_external_id"):
        StaffMember._meta.get_field("external_id").max_length,
    ("shift_overrides", "staff_member_external_id"):
        StaffMember._meta.get_field("external_id").max_length,
    ("sales", "client_external_id"):
        Client._meta.get_field("external_id").max_length,
    ("sale_items", "service_external_id"):
        Service._meta.get_field("external_id").max_length,
    ("sale_items", "product_external_id"):
        Product._meta.get_field("external_id").max_length,
    ("stock_movements", "product_external_id"):
        Product._meta.get_field("external_id").max_length,
    ("attendance_records", "staff_member_external_id"):
        StaffMember._meta.get_field("external_id").max_length,
    ("price_changes", "service_external_id"):
        Service._meta.get_field("external_id").max_length,
    ("breaks", "staff_member_external_id"):
        StaffMember._meta.get_field("external_id").max_length,
}


def _normalise_ids(data):
    """Phase-1 TF-6 pass: stringify ids in place, reject overlong.

    Runs before any reference set is built, so phase 1 and phase 2
    both see the normalised spellings. An overlong external id
    raises CommandError naming the section and record — before a
    single row is written, and never as a truncated identity.
    """
    for section, fields in _ID_FIELDS.items():
        for row in data[section]:
            if not isinstance(row, dict):
                continue
            for field in fields:
                if field in row:
                    row[field] = _norm_id(row[field])
    for (section, field), limit in _EXTERNAL_ID_LIMITS.items():
        for row in data[section]:
            if not isinstance(row, dict):
                continue
            value = row.get(field)
            if isinstance(value, str) and len(value) > limit:
                raise CommandError(
                    f"Overlong external id: section {section!r} "
                    f"record id {row.get('id')!r} has "
                    f"{field!r}={value!r} ({len(value)} characters), "
                    f"which exceeds the {limit}-character limit; "
                    f"refusing to truncate an id (truncation would "
                    f"create a different identity).")


def _check_ref(ids, old_id, what):
    if old_id not in ids:
        raise CommandError(
            f"Dangling reference: {what} id {old_id!r} not in the file.")


def _check_appt_ref(ids, ext_ids, old_id, external_id, what):
    """Appointment link check: external_id first, file id fallback.

    The link resolves if EITHER identifier names a record present
    in the file; if neither does, the reference is dangling and the
    whole file fails closed — a link is never fabricated.
    """
    external_id = _norm_id(external_id)
    if external_id and external_id in ext_ids:
        return
    if _norm_id(old_id) in ids:
        return
    raise CommandError(
        f"Dangling reference: {what} id {old_id!r} / external_id "
        f"{external_id!r} not in the file.")


def _check_price_ref(price_ids, price_pairs, row):
    """PriceChange price-link check (phase 1).

    The link resolves if the file-local ``service_price_id``
    names a price row in the file, OR the composite price
    identity — the price's service ``service_external_id`` plus
    its ``staff_level_id`` — matches a price row in the file
    (``price_pairs`` holds both spellings). Neither resolving
    means dangling: fail closed, never fabricate a link.
    """
    if _norm_id(row.get("service_price_id")) in price_ids:
        return
    external_id = _norm_id(row.get("service_external_id"))
    level_id = _norm_id(row.get("staff_level_id"))
    if external_id and (external_id, level_id) in price_pairs:
        return
    raise CommandError(
        f"Dangling reference: service_price id "
        f"{row.get('service_price_id')!r} / service_external_id "
        f"{row.get('service_external_id')!r} not in the file.")


CREATED_AT_SECTIONS = (
    "salons", "clients", "client_notes", "appointments",
    "appointment_notes", "sales", "sale_payments", "stock_movements",
)


def _checked_datetime(raw, label):
    """Parse ``raw``, requiring an explicit timezone (TF-7).

    Returns the aware datetime. Raises CommandError for a
    non-string or unparseable value and for a naive value — a
    datetime with no offset is never stored silently under USE_TZ.
    """
    if not isinstance(raw, str):
        raise CommandError(
            f"Bad datetime: {label}={raw!r} "
            f"({type(raw).__name__}), not an ISO-8601 string.")
    try:
        parsed = parse_datetime(raw)
    except (ValueError, TypeError) as exc:
        raise CommandError(
            f"Bad datetime: {label}={raw!r} cannot be parsed.") from exc
    if parsed is None:
        raise CommandError(
            f"Bad datetime: {label}={raw!r} cannot be parsed.")
    if is_naive(parsed):
        raise CommandError(
            f"Naive datetime: {label}={raw!r} has no timezone "
            f"offset; datetimes must be timezone-explicit and a "
            f"naive value is never stored or guessed into a zone.")
    return parsed


def _checked_time(raw, section):
    """Parse a phase-1 time value; missing/unparseable fails closed."""
    parsed = parse_time(raw) if isinstance(raw, str) else None
    if parsed is None:
        raise CommandError(
            f"Bad time: section {section!r} value {raw!r} "
            f"is not an ISO-8601 time string.")
    return parsed


def _checked_date(raw, section):
    """Parse a phase-1 date value; missing/unparseable fails closed."""
    parsed = parse_date(raw) if isinstance(raw, str) else None
    if parsed is None:
        raise CommandError(
            f"Bad date: section {section!r} value {raw!r} "
            f"is not an ISO-8601 date string.")
    return parsed


def _check_created_at(row, section):
    """Phase-1 TF-7 check for one record's ``created_at``.

    Absent (missing / null / empty) means no timestamp to restore
    and is not an error; a present value must parse and be aware.
    """
    raw = row.get("created_at")
    if raw is None or raw == "":
        return
    label = (
        f"section {section!r} record id {row.get('id')!r} 'created_at'")
    _checked_datetime(raw, label)


def _validate(data):
    """Phase 1: validate the whole file; write nothing.

    Checks every section's required fields and every file-local
    reference against the ids present in the file, and parses every
    service_prices amount. Raises CommandError on the first problem.
    """
    required = {
        "salons": ("id", "name"),
        "service_categories": ("id", "salon_id", "name"),
        "services": ("id", "category_id", "name", "service_minutes"),
        "staff_levels": ("id", "salon_id", "name"),
        "service_prices": ("service_id", "staff_level_id", "amount"),
        "clients": ("id", "salon_id", "first_name", "last_name"),
        "client_notes": ("client_id", "body"),
        "staff_members": ("id", "salon_id", "display_name"),
        "appointments": ("id", "client_id", "staff_member_id",
                         "start", "end"),
        "appointment_notes": ("appointment_id", "body"),
        "products": ("id", "salon_id", "name", "price"),
        "roster_patterns": ("id", "staff_member_id", "weekday",
                            "start_time", "end_time"),
        "shift_overrides": ("id", "staff_member_id", "date"),
        "sales": ("id", "salon_id", "status"),
        "sale_items": ("id", "sale_id", "kind", "unit_price"),
        "sale_payments": ("id", "sale_id", "method", "amount",
                          "status"),
        "stock_movements": ("id", "product_id", "kind",
                            "quantity_delta"),
        "attendance_records": ("id", "staff_member_id",
                               "event_type", "recorded_at"),
        "price_changes": ("id", "service_price_id", "new_amount",
                          "changed_at"),
        "refunds": ("id", "sale_id", "amount", "tender",
                    "created_at"),
        "breaks": ("id", "staff_member_id", "start", "end"),
        "cashups": ("id", "salon_id", "period_start", "period_end",
                    "total", "created_at"),
    }
    for section, fields in required.items():
        for row in data[section]:
            _require(row, section, fields)

    _normalise_ids(data)

    for section, fields in BOOL_FIELDS.items():
        for row in data[section]:
            for field in fields:
                _check_bool(row, section, field)

    for section in CREATED_AT_SECTIONS:
        for row in data[section]:
            _check_created_at(row, section)

    salon_ids = {row["id"] for row in data["salons"]}
    category_ids = {row["id"] for row in data["service_categories"]}
    level_ids = {row["id"] for row in data["staff_levels"]}
    service_ids = {row["id"] for row in data["services"]}
    client_ids = {row["id"] for row in data["clients"]}
    staff_ids = {row["id"] for row in data["staff_members"]}
    appointment_ids = {row["id"] for row in data["appointments"]}
    client_ext_ids = {
        row.get("external_id") for row in data["clients"]
        if row.get("external_id")}
    staff_ext_ids = {
        row.get("external_id") for row in data["staff_members"]
        if row.get("external_id")}
    service_ext_ids = {
        row.get("external_id") for row in data["services"]
        if row.get("external_id")}
    product_ids = {row["id"] for row in data["products"]}
    product_ext_ids = {
        row.get("external_id") for row in data["products"]
        if row.get("external_id")}
    sale_ids = {row["id"] for row in data["sales"]}
    price_ids = {row["id"] for row in data["service_prices"]
                 if "id" in row}
    service_ext_by_id = {
        row["id"]: row.get("external_id") for row in data["services"]}
    # Composite price identities present in the file, in both the
    # file-local service id spelling and the service external_id
    # spelling, each paired with the price's staff_level_id.
    price_pairs = set()
    for row in data["service_prices"]:
        price_pairs.add((row["service_id"], row["staff_level_id"]))
        ext = service_ext_by_id.get(row["service_id"])
        if ext:
            price_pairs.add((ext, row["staff_level_id"]))

    for row in data["service_categories"]:
        _check_ref(salon_ids, row["salon_id"], "salon")
    for row in data["staff_levels"]:
        _check_ref(salon_ids, row["salon_id"], "salon")
    for row in data["services"]:
        _check_ref(category_ids, row["category_id"], "category")
    for row in data["service_prices"]:
        _check_ref(service_ids, row["service_id"], "service")
        _check_ref(level_ids, row["staff_level_id"], "staff_level")
        try:
            Decimal(str(row["amount"]))
        except (InvalidOperation, ValueError) as exc:
            raise CommandError(
                f"Bad service_prices amount: {row.get('amount')!r}."
            ) from exc
    for row in data["clients"]:
        _check_ref(salon_ids, row["salon_id"], "salon")
    for row in data["client_notes"]:
        _check_ref(client_ids, row["client_id"], "client")
    for row in data["staff_members"]:
        _check_ref(salon_ids, row["salon_id"], "salon")
        if row.get("staff_level_id") is not None:
            _check_ref(level_ids, row["staff_level_id"], "staff_level")
    for row in data["appointments"]:
        _check_appt_ref(
            client_ids, client_ext_ids, row.get("client_id"),
            row.get("client_external_id"), "client")
        _check_appt_ref(
            staff_ids, staff_ext_ids, row.get("staff_member_id"),
            row.get("staff_member_external_id"), "staff_member")
        # service is nullable: both refs absent/None is the honest
        # off-book case; any ref present must resolve by one of them.
        if (row.get("service_id") is not None
                or row.get("service_external_id")):
            _check_appt_ref(
                service_ids, service_ext_ids, row.get("service_id"),
                row.get("service_external_id"), "service")
        for field in ("start", "end"):
            _checked_datetime(
                row[field], f"appointments {field} "
                f"record id {row.get('id')!r}")
        if row.get("price_override") is not None:
            try:
                Decimal(str(row["price_override"]))
            except (InvalidOperation, ValueError) as exc:
                raise CommandError(
                    f"Bad appointments price_override: "
                    f"{row.get('price_override')!r}.") from exc
        if ("status" in row
                and row["status"] not in Appointment.Status.values):
            raise CommandError(
                f"Bad appointments status: {row['status']!r}.")
        if ("origin" in row
                and row["origin"] not in Appointment.Origin.values):
            raise CommandError(
                f"Bad appointments origin: {row['origin']!r}.")
    for row in data["appointment_notes"]:
        _check_ref(appointment_ids, row["appointment_id"], "appointment")
    for row in data["roster_patterns"]:
        _check_appt_ref(
            staff_ids, staff_ext_ids, row.get("staff_member_id"),
            row.get("staff_member_external_id"), "staff_member")
        if row["weekday"] not in RosterPattern.Weekday.values:
            raise CommandError(
                f"Bad roster_patterns weekday: {row['weekday']!r}.")
        start = _checked_time(row["start_time"], "roster_patterns")
        end = _checked_time(row["end_time"], "roster_patterns")
        if end <= start:
            raise CommandError(
                f"Bad roster_patterns window: end_time {row['end_time']!r} "
                f"is not after start_time {row['start_time']!r}.")
    for row in data["shift_overrides"]:
        _check_appt_ref(
            staff_ids, staff_ext_ids, row.get("staff_member_id"),
            row.get("staff_member_external_id"), "staff_member")
        _checked_date(row["date"], "shift_overrides")
        # Model shape: a day off carries no times; a placed shift
        # carries both, end after start (shift_override_shape).
        if row.get("is_off"):
            if (row.get("start_time") is not None
                    or row.get("end_time") is not None):
                raise CommandError(
                    "Bad shift_overrides row: a day off (is_off) "
                    "must not carry start_time/end_time.")
        else:
            start = _checked_time(
                row.get("start_time"), "shift_overrides")
            end = _checked_time(row.get("end_time"), "shift_overrides")
            if end <= start:
                raise CommandError(
                    f"Bad shift_overrides window: end_time "
                    f"{row['end_time']!r} is not after start_time "
                    f"{row['start_time']!r}.")
    for row in data["products"]:
        _check_ref(salon_ids, row["salon_id"], "salon")
        try:
            Decimal(str(row["price"]))
        except (InvalidOperation, ValueError) as exc:
            raise CommandError(
                f"Bad products price: {row.get('price')!r}."
            ) from exc
        if row.get("cost_price") is not None:
            try:
                Decimal(str(row["cost_price"]))
            except (InvalidOperation, ValueError) as exc:
                raise CommandError(
                    f"Bad products cost_price: "
                    f"{row.get('cost_price')!r}.") from exc
    for row in data["sales"]:
        _check_ref(salon_ids, row["salon_id"], "salon")
        if (row.get("client_id") is not None
                or row.get("client_external_id")):
            _check_appt_ref(
                client_ids, client_ext_ids, row.get("client_id"),
                row.get("client_external_id"), "client")
        if row["status"] not in Sale.Status.values:
            raise CommandError(
                f"Bad sales status: {row['status']!r}.")
        for field in ("completed_at", "voided_at"):
            if row.get(field) is not None:
                _checked_datetime(
                    row[field], f"sales {field} "
                    f"record id {row.get('id')!r}")
    for row in data["sale_items"]:
        _check_ref(sale_ids, row["sale_id"], "sale")
        if row["kind"] not in SaleItem.Kind.values:
            raise CommandError(
                f"Bad sale_items kind: {row['kind']!r}.")
        if (row.get("service_id") is not None
                or row.get("service_external_id")):
            _check_appt_ref(
                service_ids, service_ext_ids, row.get("service_id"),
                row.get("service_external_id"), "service")
        if (row.get("product_id") is not None
                or row.get("product_external_id")):
            _check_appt_ref(
                product_ids, product_ext_ids, row.get("product_id"),
                row.get("product_external_id"), "product")
        quantity = row.get("quantity", 1)
        if (not isinstance(quantity, int)
                or isinstance(quantity, bool) or quantity < 1):
            raise CommandError(
                f"Bad sale_items quantity: {quantity!r}.")
        try:
            Decimal(str(row["unit_price"]))
        except (InvalidOperation, ValueError) as exc:
            raise CommandError(
                f"Bad sale_items unit_price: "
                f"{row.get('unit_price')!r}.") from exc
    for row in data["sale_payments"]:
        _check_ref(sale_ids, row["sale_id"], "sale")
        if row["method"] not in Payment.Method.values:
            raise CommandError(
                f"Bad sale_payments method: {row['method']!r}.")
        if row["status"] not in Payment.Status.values:
            raise CommandError(
                f"Bad sale_payments status: {row['status']!r}.")
        try:
            Decimal(str(row["amount"]))
        except (InvalidOperation, ValueError) as exc:
            raise CommandError(
                f"Bad sale_payments amount: "
                f"{row.get('amount')!r}.") from exc
    for row in data["stock_movements"]:
        _check_appt_ref(
            product_ids, product_ext_ids, row.get("product_id"),
            row.get("product_external_id"), "product")
        if row["kind"] not in StockMovement.Kind.values:
            raise CommandError(
                f"Bad stock_movements kind: {row['kind']!r}.")
        delta = row["quantity_delta"]
        if not isinstance(delta, int) or isinstance(delta, bool):
            raise CommandError(
                f"Bad stock_movements quantity_delta: {delta!r}.")
    for row in data["attendance_records"]:
        _check_appt_ref(
            staff_ids, staff_ext_ids, row.get("staff_member_id"),
            row.get("staff_member_external_id"), "staff_member")
        if row["event_type"] not in AttendanceRecord.EventType.values:
            raise CommandError(
                f"Bad attendance_records event_type: "
                f"{row['event_type']!r}.")
        _checked_datetime(
            row["recorded_at"], f"attendance_records recorded_at "
            f"record id {row.get('id')!r}")
    for row in data["price_changes"]:
        _check_price_ref(price_ids, price_pairs, row)
        # changed_at is the idempotency anchor: required and
        # timezone-explicit (TF-7), like attendance recorded_at.
        _checked_datetime(
            row["changed_at"], f"price_changes changed_at "
            f"record id {row.get('id')!r}")
        for field in ("old_amount", "new_amount"):
            if row.get(field) is not None:
                try:
                    Decimal(str(row[field]))
                except (InvalidOperation, ValueError) as exc:
                    raise CommandError(
                        f"Bad price_changes {field}: "
                        f"{row.get(field)!r}.") from exc
    for row in data["refunds"]:
        _check_ref(sale_ids, row["sale_id"], "sale")
        if row["tender"] not in Payment.Method.values:
            raise CommandError(
                f"Bad refunds tender: {row['tender']!r}.")
        # created_at is the idempotency anchor: required and
        # timezone-explicit (TF-7), like price_changes changed_at.
        _checked_datetime(
            row["created_at"], f"refunds created_at "
            f"record id {row.get('id')!r}")
        try:
            Decimal(str(row["amount"]))
        except (InvalidOperation, ValueError) as exc:
            raise CommandError(
                f"Bad refunds amount: {row.get('amount')!r}."
            ) from exc
    for row in data["breaks"]:
        _check_appt_ref(
            staff_ids, staff_ext_ids, row.get("staff_member_id"),
            row.get("staff_member_external_id"), "staff_member")
        for field in ("start", "end"):
            _checked_datetime(
                row[field], f"breaks {field} "
                f"record id {row.get('id')!r}")
    for row in data["cashups"]:
        _check_ref(salon_ids, row["salon_id"], "salon")
        for field in ("period_start", "period_end", "created_at"):
            _checked_datetime(
                row[field], f"cashups {field} "
                f"record id {row.get('id')!r}")
        try:
            Decimal(str(row["total"]))
        except (InvalidOperation, ValueError) as exc:
            raise CommandError(
                f"Bad cashups total: {row.get('total')!r}."
            ) from exc
        tender_totals = row.get("tender_totals", {})
        if not isinstance(tender_totals, dict):
            raise CommandError(
                f"Bad cashups tender_totals: {tender_totals!r} "
                f"is not an object.")
        for key, value in tender_totals.items():
            if key not in Payment.Method.values:
                raise CommandError(
                    f"Bad cashups tender_totals key: {key!r}.")
            if not isinstance(value, str):
                raise CommandError(
                    f"Bad cashups tender_totals value: "
                    f"{key!r}={value!r} is not a string.")
            try:
                Decimal(value)
            except (InvalidOperation, ValueError) as exc:
                raise CommandError(
                    f"Bad cashups tender_totals value: "
                    f"{key!r}={value!r}.") from exc


def _ref(mapping, old_id, what):
    try:
        return mapping[old_id]
    except KeyError:
        raise CommandError(
            f"Dangling reference: {what} id {old_id!r} not in the file."
        ) from None


def _by_external(rows, mapping):
    return {
        _norm_id(row["external_id"]): mapping[_norm_id(row["id"])]
        for row in rows if row.get("external_id")
    }


def _resolve_appt_ref(by_id, by_ext, row, id_field, ext_field, what):
    """Resolve an appointment link: external_id first, id fallback."""
    external_id = _norm_id(row.get(ext_field))
    if external_id and external_id in by_ext:
        return by_ext[external_id]
    return _ref(by_id, _norm_id(row.get(id_field)), what)


def _resolve_price_ref(prices, prices_by_pair, levels, services_by_ext,
                       row):
    """Resolve a PriceChange's price: external identity first.

    The price's own identity is (service, staff_level): try the
    price whose service matches ``service_external_id`` and whose
    level matches ``staff_level_id``; fall back to the file-local
    ``service_price_id`` map, like the other sections' parents.
    """
    external_id = _norm_id(row.get("service_external_id"))
    service = services_by_ext.get(external_id) if external_id else None
    level = levels.get(_norm_id(row.get("staff_level_id")))
    if service is not None and level is not None:
        price = prices_by_pair.get((service.pk, level.pk))
        if price is not None:
            return price
    return _ref(prices, _norm_id(row.get("service_price_id")),
                "service_price")


def _restore_created_at(obj, raw):
    """Best-effort restore of an exported created_at timestamp.

    Absent values skip; present values must already have passed
    phase 1, and are re-checked here so a naive or unparseable
    value can never reach the database even if validation changes.
    """
    if not raw:
        return
    parsed = _checked_datetime(
        raw, f"{type(obj).__name__} 'created_at'")
    if obj.created_at != parsed:
        type(obj).objects.filter(pk=obj.pk).update(created_at=parsed)
        obj.created_at = parsed


class Command(BaseCommand):
    help = "Import salon core data from an export_salon_data JSON file."

    def add_arguments(self, parser):
        parser.add_argument("input", help="Path of the export JSON file to load.")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print a per-section JSON dry-run report "
                 "(saloncore.dry_run) for the source file and "
                 "write nothing to the database.")

    @transaction.atomic
    def handle(self, *args, **options):
        data = _load(options["input"])
        # Phase 1: validate everything before writing anything.
        _validate(data)

        if options.get("dry_run"):
            # Zero writes: report per section and return before
            # phase 2. Mapped keys per section are KNOWN_KEYS —
            # every key this importer consumes in that section.
            record_sets = {
                section: (data[section], KNOWN_KEYS[section])
                for section in SECTIONS if section in data
            }
            self.stdout.write(json.dumps(
                build_dry_run_reports(record_sets), sort_keys=True))
            return

        # Phase 2: write (all references/required data already proven).
        salons = {}
        for row in data["salons"]:
            obj, _ = Salon.objects.update_or_create(
                name=row["name"],
                defaults={
                    "timezone": row.get("timezone", "UTC"),
                    "currency": row.get("currency", "USD"),
                },
            )
            _restore_created_at(obj, row.get("created_at"))
            salons[row["id"]] = obj

        categories = {}
        for row in data["service_categories"]:
            obj, _ = ServiceCategory.objects.update_or_create(
                salon=_ref(salons, row["salon_id"], "salon"),
                name=row["name"],
                defaults={
                    "sort_order": row.get("sort_order", 0),
                    "active": row["active"],
                },
            )
            categories[row["id"]] = obj

        levels = {}
        for row in data["staff_levels"]:
            obj, _ = StaffLevel.objects.update_or_create(
                salon=_ref(salons, row["salon_id"], "salon"),
                name=row["name"],
                defaults={
                    "sort_order": row.get("sort_order", 0),
                    "active": row["active"],
                },
            )
            levels[row["id"]] = obj

        services = {}
        for row in data["services"]:
            defaults = {
                "name": row["name"],
                "category": _ref(categories, row["category_id"], "category"),
                "description": row.get("description", ""),
                "service_minutes": row["service_minutes"],
                "processing_minutes": row.get("processing_minutes", 0),
                "finishing_minutes": row.get("finishing_minutes", 0),
                "active": row["active"],
            }
            if "payload" in row:
                defaults["payload"] = row["payload"]
            external_id = _norm_id(row.get("external_id")) or ""
            if external_id:
                obj, _ = Service.objects.update_or_create(
                    external_id=external_id, defaults=defaults)
            else:
                obj, _ = Service.objects.update_or_create(
                    category=defaults["category"], name=row["name"],
                    defaults=defaults)
            services[row["id"]] = obj

        prices = {}
        prices_by_pair = {}
        for row in data["service_prices"]:
            try:
                amount = Decimal(str(row["amount"]))
            except (InvalidOperation, ValueError, KeyError) as exc:
                raise CommandError(
                    f"Bad service_prices amount: {row.get('amount')!r}."
                ) from exc
            price_obj, _ = ServicePrice.objects.update_or_create(
                service=_ref(services, row["service_id"], "service"),
                staff_level=_ref(levels, row["staff_level_id"], "staff_level"),
                defaults={
                    "amount": amount,
                    "is_from": row["is_from"],
                    "active": row["active"],
                },
            )
            if row.get("id") is not None:
                prices[row["id"]] = price_obj
            prices_by_pair[
                (price_obj.service_id, price_obj.staff_level_id)
            ] = price_obj

        clients = {}
        for row in data["clients"]:
            defaults = {
                "first_name": row["first_name"],
                "last_name": row["last_name"],
                "email": row.get("email", ""),
                "phone": row.get("phone", ""),
                "sms_opt_in": row.get("sms_opt_in", False),
                "email_opt_in": row.get("email_opt_in", False),
                "active": row["active"],
            }
            if "payload" in row:
                defaults["payload"] = row["payload"]
            salon = _ref(salons, row["salon_id"], "salon")
            external_id = _norm_id(row.get("external_id")) or ""
            if external_id:
                obj, _ = Client.objects.update_or_create(
                    salon=salon, external_id=external_id, defaults=defaults)
            else:
                obj, _ = Client.objects.update_or_create(
                    salon=salon, first_name=row["first_name"],
                    last_name=row["last_name"], email=defaults["email"],
                    phone=defaults["phone"], defaults=defaults)
            _restore_created_at(obj, row.get("created_at"))
            clients[row["id"]] = obj

        for row in data["client_notes"]:
            obj, _ = ClientNote.objects.update_or_create(
                client=_ref(clients, row["client_id"], "client"),
                body=row["body"],
                author_name=row.get("author_name", ""),
                defaults={},
            )
            _restore_created_at(obj, row.get("created_at"))

        staff_members = {}
        for row in data["staff_members"]:
            defaults = {
                "display_name": row["display_name"],
                "staff_level": (
                    _ref(levels, row["staff_level_id"], "staff_level")
                    if row.get("staff_level_id") is not None else None
                ),
                "online_bookable": row["online_bookable"],
                "active": row["active"],
            }
            salon = _ref(salons, row["salon_id"], "salon")
            external_id = _norm_id(row.get("external_id")) or ""
            if external_id:
                obj, _ = StaffMember.objects.update_or_create(
                    salon=salon, external_id=external_id, defaults=defaults)
            else:
                obj, _ = StaffMember.objects.update_or_create(
                    salon=salon, display_name=row["display_name"],
                    defaults=defaults)
            staff_members[row["id"]] = obj

        clients_by_ext = _by_external(data["clients"], clients)
        staff_by_ext = _by_external(data["staff_members"], staff_members)
        services_by_ext = _by_external(data["services"], services)

        appointments = {}
        for row in data["appointments"]:
            client = _resolve_appt_ref(
                clients, clients_by_ext, row,
                "client_id", "client_external_id", "client")
            staff_member = _resolve_appt_ref(
                staff_members, staff_by_ext, row,
                "staff_member_id", "staff_member_external_id",
                "staff_member")
            if (row.get("service_id") is None
                    and not row.get("service_external_id")):
                service = None
            else:
                service = _resolve_appt_ref(
                    services, services_by_ext, row,
                    "service_id", "service_external_id", "service")
            defaults = {
                "client": client, "staff_member": staff_member,
                "service": service,
                "service_name": row.get("service_name", ""),
                "start": _checked_datetime(
                    row["start"], "appointments start"),
                "end": _checked_datetime(row["end"], "appointments end"),
                "status": row.get("status", Appointment.Status.BOOKED),
                "origin": row.get("origin", Appointment.Origin.UNKNOWN),
                "price_override": (
                    Decimal(str(row["price_override"]))
                    if row.get("price_override") is not None else None
                ),
            }
            if "payload" in row:
                defaults["payload"] = row["payload"]
            external_id = _norm_id(row.get("external_id")) or ""
            if external_id:
                obj, _ = Appointment.objects.update_or_create(
                    external_id=external_id, defaults=defaults)
            else:
                obj, _ = Appointment.objects.update_or_create(
                    client=client, staff_member=staff_member,
                    start=defaults["start"], end=defaults["end"],
                    defaults={
                        k: v for k, v in defaults.items()
                        if k not in ("client", "staff_member",
                                     "start", "end")
                    })
            _restore_created_at(obj, row.get("created_at"))
            appointments[row["id"]] = obj

        for row in data["appointment_notes"]:
            obj, _ = AppointmentNote.objects.update_or_create(
                appointment=_ref(
                    appointments, row["appointment_id"], "appointment"),
                body=row["body"],
                author_name=row.get("author_name", ""),
                defaults={},
            )
            _restore_created_at(obj, row.get("created_at"))

        for row in data["roster_patterns"]:
            staff_member = _resolve_appt_ref(
                staff_members, staff_by_ext, row,
                "staff_member_id", "staff_member_external_id",
                "staff_member")
            RosterPattern.objects.update_or_create(
                staff_member=staff_member,
                weekday=row["weekday"],
                start_time=parse_time(row["start_time"]),
                end_time=parse_time(row["end_time"]),
                defaults={"active": row["active"]},
            )

        for row in data["shift_overrides"]:
            staff_member = _resolve_appt_ref(
                staff_members, staff_by_ext, row,
                "staff_member_id", "staff_member_external_id",
                "staff_member")
            ShiftOverride.objects.update_or_create(
                staff_member=staff_member,
                date=parse_date(row["date"]),
                defaults={
                    "is_off": row["is_off"],
                    "start_time": (
                        parse_time(row["start_time"])
                        if row.get("start_time") is not None else None
                    ),
                    "end_time": (
                        parse_time(row["end_time"])
                        if row.get("end_time") is not None else None
                    ),
                },
            )

        products = {}
        for row in data["products"]:
            defaults = {
                "name": row["name"],
                "sku": row.get("sku", ""),
                "barcode": row.get("barcode", ""),
                "price": Decimal(str(row["price"])),
                "cost_price": (
                    Decimal(str(row["cost_price"]))
                    if row.get("cost_price") is not None else None
                ),
                "active": row["active"],
                "brand_name": row.get("brand_name", ""),
                "category_name": row.get("category_name", ""),
                "product_type": row.get("product_type", ""),
            }
            if "payload" in row:
                defaults["payload"] = row["payload"]
            salon = _ref(salons, row["salon_id"], "salon")
            external_id = _norm_id(row.get("external_id")) or ""
            if external_id:
                obj, _ = Product.objects.update_or_create(
                    external_id=external_id,
                    defaults={**defaults, "salon": salon})
            else:
                obj, _ = Product.objects.update_or_create(
                    salon=salon, name=row["name"],
                    sku=defaults["sku"], barcode=defaults["barcode"],
                    defaults=defaults)
            products[row["id"]] = obj

        products_by_ext = _by_external(data["products"], products)

        sales = {}
        for row in data["sales"]:
            if (row.get("client_id") is None
                    and not row.get("client_external_id")):
                client = None
            else:
                client = _resolve_appt_ref(
                    clients, clients_by_ext, row,
                    "client_id", "client_external_id", "client")
            completed_at = (
                _checked_datetime(row["completed_at"],
                                    "sales completed_at")
                if row.get("completed_at") is not None else None)
            voided_at = (
                _checked_datetime(row["voided_at"], "sales voided_at")
                if row.get("voided_at") is not None else None)
            # created_at is the identity anchor: parse it for the
            # lookup before _restore_created_at fixes the stored row.
            created_raw = row.get("created_at")
            lookup_created = (
                _checked_datetime(created_raw, "sales created_at")
                if created_raw else None)
            defaults = {
                "status": row["status"],
                "completed_at": completed_at,
                "voided_at": voided_at,
                "void_reason": row.get("void_reason", ""),
            }
            salon = _ref(salons, row["salon_id"], "salon")
            if lookup_created is not None:
                obj, _ = Sale.objects.update_or_create(
                    salon=salon, client=client,
                    created_at=lookup_created,
                    completed_at=completed_at, voided_at=voided_at,
                    defaults=defaults)
            else:
                obj, _ = Sale.objects.update_or_create(
                    salon=salon, client=client, status=row["status"],
                    completed_at=completed_at, voided_at=voided_at,
                    defaults=defaults)
            _restore_created_at(obj, created_raw)
            sales[row["id"]] = obj

        for row in data["sale_items"]:
            service = None
            if (row.get("service_id") is not None
                    or row.get("service_external_id")):
                service = _resolve_appt_ref(
                    services, services_by_ext, row,
                    "service_id", "service_external_id", "service")
            product = None
            if (row.get("product_id") is not None
                    or row.get("product_external_id")):
                product = _resolve_appt_ref(
                    products, products_by_ext, row,
                    "product_id", "product_external_id", "product")
            SaleItem.objects.update_or_create(
                sale=_ref(sales, row["sale_id"], "sale"),
                kind=row["kind"], service=service, product=product,
                description=row.get("description", ""),
                defaults={
                    "quantity": row.get("quantity", 1),
                    "unit_price": Decimal(str(row["unit_price"])),
                },
            )

        for row in data["sale_payments"]:
            created_raw = row.get("created_at")
            lookup_created = (
                _checked_datetime(created_raw,
                                  "sale_payments created_at")
                if created_raw else None)
            defaults = {
                "amount": Decimal(str(row["amount"])),
                "status": row["status"],
            }
            sale = _ref(sales, row["sale_id"], "sale")
            if lookup_created is not None:
                obj, _ = Payment.objects.update_or_create(
                    sale=sale, method=row["method"],
                    created_at=lookup_created, defaults=defaults)
            else:
                obj, _ = Payment.objects.update_or_create(
                    sale=sale, method=row["method"],
                    amount=defaults["amount"], status=row["status"],
                    defaults={})
            _restore_created_at(obj, created_raw)

        for row in data["stock_movements"]:
            product = _resolve_appt_ref(
                products, products_by_ext, row,
                "product_id", "product_external_id", "product")
            created_raw = row.get("created_at")
            lookup_created = (
                _checked_datetime(created_raw,
                                  "stock_movements created_at")
                if created_raw else None)
            if lookup_created is not None:
                obj, _ = StockMovement.objects.update_or_create(
                    product=product, kind=row["kind"],
                    quantity_delta=row["quantity_delta"],
                    note=row.get("note", ""),
                    created_at=lookup_created, defaults={})
            else:
                obj, _ = StockMovement.objects.update_or_create(
                    product=product, kind=row["kind"],
                    quantity_delta=row["quantity_delta"],
                    note=row.get("note", ""), defaults={})
            _restore_created_at(obj, created_raw)

        for row in data["attendance_records"]:
            staff_member = _resolve_appt_ref(
                staff_members, staff_by_ext, row,
                "staff_member_id", "staff_member_external_id",
                "staff_member")
            AttendanceRecord.objects.update_or_create(
                staff_member=staff_member,
                recorded_at=_checked_datetime(
                    row["recorded_at"],
                    "attendance_records recorded_at"),
                event_type=row["event_type"],
                defaults={"note": row.get("note", "")},
            )

        for row in data["price_changes"]:
            price = _resolve_price_ref(
                prices, prices_by_pair, levels, services_by_ext, row)
            changed_at = _checked_datetime(
                row["changed_at"], "price_changes changed_at")
            # Append-only history: get_or_create on the natural
            # key — an already-restored change is returned
            # untouched, never updated and never duplicated.
            change, created = PriceChange.objects.get_or_create(
                service_price=price,
                changed_at=changed_at,
                old_amount=(
                    Decimal(str(row["old_amount"]))
                    if row.get("old_amount") is not None else None),
                new_amount=Decimal(str(row["new_amount"])),
                changed_by=row.get("changed_by", ""),
                note=row.get("note", ""),
            )
            if created and change.changed_at != changed_at:
                # Creation stamped auto_now_add; re-stamp the
                # exported instant once, at creation only, via a
                # plain queryset (PriceChangeQuerySet.update is
                # blocked by design — see the module docstring).
                PlainQuerySet(
                    model=PriceChange, using="default").filter(
                        pk=change.pk).update(changed_at=changed_at)
                change.changed_at = changed_at

        for row in data["refunds"]:
            created_at = _checked_datetime(
                row["created_at"], "refunds created_at")
            # Append-only: get_or_create on the natural key —
            # an already-restored refund is returned untouched,
            # never updated and never duplicated.
            refund, created = Refund.objects.get_or_create(
                sale=_ref(sales, row["sale_id"], "sale"),
                amount=Decimal(str(row["amount"])),
                reason=row.get("reason", ""),
                tender=row["tender"],
                created_at=created_at,
            )
            if created:
                # Creation stamped auto_now_add; re-stamp the
                # exported instant once, at creation only.
                _restore_created_at(refund, row.get("created_at"))

        for row in data["breaks"]:
            staff_member = _resolve_appt_ref(
                staff_members, staff_by_ext, row,
                "staff_member_id", "staff_member_external_id",
                "staff_member")
            Break.objects.get_or_create(
                staff_member=staff_member,
                start=_checked_datetime(row["start"], "breaks start"),
                end=_checked_datetime(row["end"], "breaks end"),
                defaults={"paid": row["paid"]},
            )
        for row in data["cashups"]:
            period_start = _checked_datetime(
                row["period_start"], "cashups period_start")
            period_end = _checked_datetime(
                row["period_end"], "cashups period_end")
            created_at = _checked_datetime(
                row["created_at"], "cashups created_at")
            # Snapshot: get_or_create on the natural key — an
            # already-restored cashup is returned untouched,
            # never updated and never duplicated.
            cashup, created = Cashup.objects.get_or_create(
                salon=_ref(salons, row["salon_id"], "salon"),
                period_start=period_start,
                period_end=period_end,
                created_at=created_at,
                defaults={
                    "tender_totals": row.get("tender_totals", {}),
                    "total": Decimal(str(row["total"])),
                    "note": row.get("note", ""),
                },
            )
            if created:
                _restore_created_at(cashup, row.get("created_at"))

        summary = ", ".join(
            f"{section}={len(data[section])}" for section in SECTIONS
        )
        self.stdout.write(f"IMPORT_SUMMARY {summary}")
        unknown_sections, unknown_keys = _unknown_drops(data)
        self.stdout.write(
            "IMPORT_DROPPED "
            f"unknown_sections={','.join(unknown_sections) or 'none'} "
            f"unknown_keys={','.join(unknown_keys) or 'none'}")
        self.stdout.write(f"Imported {options['input']}")
