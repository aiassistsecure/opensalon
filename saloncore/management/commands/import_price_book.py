"""Import a price book (categories, services, staff levels, prices).

Usage:
    python manage.py import_price_book services.json [--salon NAME]
        [--staff staff.json] [--base-level NAME]

The input shape is the services export of the salon's previous system:
a JSON list of service objects with ``name``, ``categoryName``,
``duration`` (minutes), ``gapTime``, ``price`` (the base price),
``archived``, ``internetDescription`` and optionally
``staffCategories: {"prices": [{"id": ..., "price": ...}]}`` — per-level
prices keyed by staff-category id — plus per-person ``userPrices``.

Mapping (one source of truth — this command is the only writer here):

- Category  <- ``categoryName`` (fallback: ``categoryId``, then
  "Uncategorized"), scoped to the salon.
- Service   <- one row per (category, name); ``duration`` becomes
  ``service_minutes``, ``gapTime`` becomes ``processing_minutes``,
  ``internetDescription`` becomes ``description``, ``archived``
  becomes ``active=False``.
- StaffLevel <- each distinct ``staffCategories.prices`` id. With
  ``--staff`` (a staff export in the same system's shape), ids that are
  staff *category* ids resolve to their category names (e.g.
  "Artist Level 6"); ids that belong to an individual staff member are
  NOT level prices and are skipped (counted in the summary). Without
  ``--staff`` every id becomes a level named by that id.
- ServicePrice <- the base ``price`` attaches to a level named by
  ``--base-level`` (default "Base"); each staff-category price attaches
  to its level. Per-person ``userPrices`` are skipped and counted —
  ServicePrice is per level by design, never per person.

Idempotent: every row is written with ``update_or_create`` keyed by its
natural identity above, so re-running updates in place and never
duplicates. When a re-import changes an existing price amount, a
PriceChange audit row is appended (changed_by="import_price_book").
The import runs in one transaction: a bad file changes nothing.
"""

import json
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from saloncore.models import (
    PriceChange,
    Salon,
    Service,
    ServiceCategory,
    ServicePrice,
    StaffLevel,
)

BASE_LEVEL_DEFAULT = "Base"


def _decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _load_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise CommandError(f"Cannot read {what} file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"{what} file {path} is not valid JSON: {exc}") from exc


class Command(BaseCommand):
    help = "Import service categories, services, staff levels and prices from a JSON export."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the services JSON export.")
        parser.add_argument("--salon", default="My Salon",
                            help="Salon name to import into (created if missing).")
        parser.add_argument("--staff", default=None,
                            help="Optional staff JSON export, used to resolve "
                                 "staff-category ids to level names.")
        parser.add_argument("--base-level", default=BASE_LEVEL_DEFAULT,
                            help="Staff level name the base price attaches to.")

    def handle(self, *args, **options):
        data = _load_json(options["path"], "services")
        if isinstance(data, dict):
            data = data.get("services", [])
        if not isinstance(data, list):
            raise CommandError("Services file must be a JSON list of services.")

        category_names, user_category = {}, {}
        if options["staff"]:
            staff = _load_json(options["staff"], "staff")
            for row in staff if isinstance(staff, list) else []:
                cid, name = row.get("staffCategoryId"), row.get("staffCategoryName")
                if cid and name:
                    category_names[cid] = name
                uid = row.get("userId") or row.get("staffId")
                if uid and name:
                    user_category[uid] = name

        stats = dict.fromkeys(
            ["services", "categories", "levels", "prices",
             "skipped_services", "skipped_individual_prices"], 0)

        with transaction.atomic():
            salon, _ = Salon.objects.get_or_create(name=options["salon"])
            levels = {}

            def level_for(level_id):
                """StaffLevel for a staff-category id, or None if the id
                belongs to an individual (not a level) and names are known."""
                if level_id in levels:
                    return levels[level_id]
                if level_id in category_names:
                    name = category_names[level_id]
                elif level_id in user_category or (
                        category_names and level_id not in category_names):
                    return None
                else:
                    name = level_id
                level, created = StaffLevel.objects.get_or_create(
                    salon=salon, name=name)
                levels[level_id] = level
                stats["levels"] += int(created)
                return level

            def set_price(service, level, amount):
                old = ServicePrice.objects.filter(
                    service=service, staff_level=level).first()
                price, created = ServicePrice.objects.update_or_create(
                    service=service, staff_level=level,
                    defaults={"amount": amount, "active": True})
                stats["prices"] += int(created)
                if old and not created and old.amount != amount:
                    PriceChange.objects.create(
                        service_price=price, changed_by="import_price_book",
                        old_amount=old.amount, new_amount=amount,
                        note="Price book import")
                return price

            base_level = None
            for row in data:
                if not isinstance(row, dict) or not row.get("name"):
                    stats["skipped_services"] += 1
                    continue
                cat_name = (row.get("categoryName") or row.get("categoryId")
                            or "Uncategorized")
                category, created = ServiceCategory.objects.get_or_create(
                    salon=salon, name=cat_name)
                stats["categories"] += int(created)
                service, created = Service.objects.update_or_create(
                    category=category, name=row["name"],
                    defaults={
                        "description": row.get("internetDescription")
                                       or row.get("description") or "",
                        "service_minutes": int(row.get("duration") or 0),
                        "processing_minutes": int(row.get("gapTime") or 0),
                        "active": not row.get("archived", False),
                    })
                stats["services"] += int(created)

                amount = _decimal(row.get("price"))
                if amount is not None:
                    if base_level is None:
                        base_level, created = StaffLevel.objects.get_or_create(
                            salon=salon, name=options["base_level"])
                        stats["levels"] += int(created)
                    set_price(service, base_level, amount)

                for entry in (row.get("staffCategories") or {}).get("prices") or []:
                    level_amount = _decimal(entry.get("price"))
                    level = level_for(entry.get("id")) if entry.get("id") else None
                    if level is None or level_amount is None:
                        stats["skipped_individual_prices"] += 1
                        continue
                    set_price(service, level, level_amount)
                # Per-person prices are not level prices; count and skip.
                stats["skipped_individual_prices"] += len(row.get("userPrices") or [])

        self.stdout.write(
            "Imported price book for {salon}: {services} services, "
            "{categories} categories, {levels} staff levels, {prices} prices "
            "created; {skipped_services} services skipped, "
            "{skipped_individual_prices} per-person prices skipped.".format(
                salon=options["salon"], **stats))
        # Machine-readable line for validation runs.
        self.stdout.write("IMPORT_SUMMARY " + json.dumps(
            {"salon": options["salon"], **stats}, sort_keys=True))
