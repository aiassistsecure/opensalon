"""Import salon core data from an export_salon_data JSON file.

Usage:
    python manage.py import_salon_data INPUT.json

This is the restore side of the Exit Test: it consumes exactly the
JSON format written by ``export_salon_data`` (see that command for the
section list) and restores Salon, ServiceCategory, Service,
StaffLevel, ServicePrice, Client, ClientNote and StaffMember records.

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

No provider concepts: external ids are the generic fields the models
already carry. The import runs in one transaction — a bad file (bad
JSON, missing sections, dangling references, counts that disagree
with the sections) changes nothing.
"""

import json
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime

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


def _ref(mapping, old_id, what):
    try:
        return mapping[old_id]
    except KeyError:
        raise CommandError(
            f"Dangling reference: {what} id {old_id!r} not in the file."
        ) from None


def _restore_created_at(obj, raw):
    """Best-effort restore of an exported created_at timestamp."""
    if not raw:
        return
    parsed = parse_datetime(raw)
    if parsed is not None and obj.created_at != parsed:
        type(obj).objects.filter(pk=obj.pk).update(created_at=parsed)
        obj.created_at = parsed


class Command(BaseCommand):
    help = "Import salon core data from an export_salon_data JSON file."

    def add_arguments(self, parser):
        parser.add_argument("input", help="Path of the export JSON file to load.")

    @transaction.atomic
    def handle(self, *args, **options):
        data = _load(options["input"])

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
                    "active": row.get("active", True),
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
                    "active": row.get("active", True),
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
                "active": row.get("active", True),
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
                    "is_from": row.get("is_from", False),
                    "active": row.get("active", True),
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
                "active": row.get("active", True),
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

        for row in data["staff_members"]:
            defaults = {
                "display_name": row["display_name"],
                "staff_level": (
                    _ref(levels, row["staff_level_id"], "staff_level")
                    if row.get("staff_level_id") is not None else None
                ),
                "online_bookable": row.get("online_bookable", True),
                "active": row.get("active", True),
            }
            salon = _ref(salons, row["salon_id"], "salon")
            external_id = row.get("external_id") or ""
            if external_id:
                StaffMember.objects.update_or_create(
                    salon=salon, external_id=external_id, defaults=defaults)
            else:
                StaffMember.objects.update_or_create(
                    salon=salon, display_name=row["display_name"],
                    defaults=defaults)

        summary = ", ".join(
            f"{section}={len(data[section])}" for section in SECTIONS
        )
        self.stdout.write(f"IMPORT_SUMMARY {summary}")
        self.stdout.write(f"Imported {options['input']}")
