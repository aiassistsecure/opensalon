"""Import salon core data from an export_salon_data JSON file.

Usage:
    python manage.py import_salon_data INPUT.json

This is the restore side of the Exit Test: it consumes exactly the
JSON format written by ``export_salon_data`` (see that command for the
section list) and restores Salon, ServiceCategory, Service,
StaffLevel, ServicePrice, Client, ClientNote, StaffMember,
Appointment and AppointmentNote records.

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
service_prices, clients, staff_members), ``is_from``
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
"""

import json
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive

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

SECTIONS = (
    "salons", "service_categories", "services", "staff_levels",
    "service_prices", "clients", "client_notes", "staff_members",
    "appointments", "appointment_notes",
)


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
        if not isinstance(data.get(section), list):
            raise CommandError(f"Import file is missing section {section!r}.")
    counts = data.get("counts")
    if counts is not None:
        for section in SECTIONS:
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
    if external_id and external_id in ext_ids:
        return
    if old_id in ids:
        return
    raise CommandError(
        f"Dangling reference: {what} id {old_id!r} / external_id "
        f"{external_id!r} not in the file.")


CREATED_AT_SECTIONS = (
    "salons", "clients", "client_notes", "appointments",
    "appointment_notes",
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
    }
    for section, fields in required.items():
        for row in data[section]:
            _require(row, section, fields)

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


def _ref(mapping, old_id, what):
    try:
        return mapping[old_id]
    except KeyError:
        raise CommandError(
            f"Dangling reference: {what} id {old_id!r} not in the file."
        ) from None


def _by_external(rows, mapping):
    return {
        row["external_id"]: mapping[row["id"]]
        for row in rows if row.get("external_id")
    }


def _resolve_appt_ref(by_id, by_ext, row, id_field, ext_field, what):
    """Resolve an appointment link: external_id first, id fallback."""
    external_id = row.get(ext_field)
    if external_id and external_id in by_ext:
        return by_ext[external_id]
    return _ref(by_id, row.get(id_field), what)


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

    @transaction.atomic
    def handle(self, *args, **options):
        data = _load(options["input"])
        # Phase 1: validate everything before writing anything.
        _validate(data)

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
            external_id = row.get("external_id") or ""
            if external_id:
                obj, _ = Service.objects.update_or_create(
                    external_id=external_id, defaults=defaults)
            else:
                obj, _ = Service.objects.update_or_create(
                    category=defaults["category"], name=row["name"],
                    defaults=defaults)
            services[row["id"]] = obj

        for row in data["service_prices"]:
            try:
                amount = Decimal(str(row["amount"]))
            except (InvalidOperation, ValueError, KeyError) as exc:
                raise CommandError(
                    f"Bad service_prices amount: {row.get('amount')!r}."
                ) from exc
            ServicePrice.objects.update_or_create(
                service=_ref(services, row["service_id"], "service"),
                staff_level=_ref(levels, row["staff_level_id"], "staff_level"),
                defaults={
                    "amount": amount,
                    "is_from": row["is_from"],
                    "active": row["active"],
                },
            )

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
            salon = _ref(salons, row["salon_id"], "salon")
            external_id = row.get("external_id") or ""
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
            external_id = row.get("external_id") or ""
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
            external_id = row.get("external_id") or ""
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

        summary = ", ".join(
            f"{section}={len(data[section])}" for section in SECTIONS
        )
        self.stdout.write(f"IMPORT_SUMMARY {summary}")
        self.stdout.write(f"Imported {options['input']}")
