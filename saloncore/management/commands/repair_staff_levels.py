"""Repair staff-level identity after a staff-less price import.

Usage:
    python manage.py repair_staff_levels --staff staff.json
        [--salon NAME]

The price-book import names a level by its source id unless the
staff export is passed alongside (``import_price_book --staff``),
which is how a salon ends up with two halves of one ladder: named
levels holding every staff member and no prices, and id-named
levels holding every price and no members — with the day book
falling back to Base prices because the join never lands.

This command rejoins them, using the staff export as the bridge
(it pairs every staff-category id with its human name):

- A level named by a category id whose named twin exists is
  MERGED into the twin: prices move (identical duplicates are
  dropped as the same fact; a differing price for the same service
  is a conflict — the level is then left in place, renamed
  "<Name> (duplicate — review)", and reported, never overwritten),
  members are re-pointed, and the id-named level is deleted.
- A level named by a category id with no twin is simply renamed
  to the category's human name.
- A level named by an id the staff export does not know (a former
  staff member's personal price ref, most likely) keeps its prices
  and is renamed "Unassigned ····XXXX" (its last four characters) —
  readable on the page, honest about being ownerless.

Named levels and the Base level are never touched. The command is
idempotent: a second run finds nothing to do. Amounts are never
changed; this is identity repair, not repricing.
"""

import json
import re

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon, ServicePrice, StaffLevel

_ID_LIKE = re.compile(r"^[A-Za-z0-9_\-]{16,}$")


def _is_id_like(name):
    return bool(_ID_LIKE.match(name or ""))


class Command(BaseCommand):
    help = "Merge id-named staff levels into their named twins."

    def add_arguments(self, parser):
        parser.add_argument("--staff", required=True,
                            help="Staff export JSON (the bridge data).")
        parser.add_argument("--salon", default="",
                            help="Salon name (default: the only/first).")

    def handle(self, *args, **options):
        try:
            with open(options["staff"], encoding="utf-8") as handle:
                rows = json.load(handle)
        except (OSError, ValueError) as exc:
            raise CommandError(f"cannot read staff export: {exc}") from exc
        if isinstance(rows, dict):
            rows = rows.get("items", rows.get("data", []))
        categories = {}
        for row in rows:
            cid, cname = row.get("staffCategoryId"), row.get("staffCategoryName")
            if cid and cname:
                categories[str(cid).lower()] = cname

        salon_qs = Salon.objects.order_by("id")
        if options["salon"]:
            salon_qs = salon_qs.filter(name=options["salon"])
        salon = salon_qs.first()
        if salon is None:
            raise CommandError("no salon found")

        merged = renamed = unassigned = conflicts = 0
        for level in list(StaffLevel.objects.filter(salon=salon)):
            if not _is_id_like(level.name):
                continue
            cat_name = categories.get(level.name.lower())
            if cat_name is None:
                label = f"Unassigned ····{level.name[-4:]}"
                if label != level.name and not StaffLevel.objects.filter(
                    salon=salon, name=label
                ).exclude(pk=level.pk).exists():
                    level.name = label
                    level.save(update_fields=["name"])
                    unassigned += 1
                continue
            twin = (
                StaffLevel.objects.filter(salon=salon, name=cat_name)
                .exclude(pk=level.pk)
                .first()
            )
            if twin is None:
                level.name = cat_name
                level.save(update_fields=["name"])
                renamed += 1
                continue
            prices = list(ServicePrice.objects.filter(staff_level=level))
            differing = []
            for price in prices:
                existing = ServicePrice.objects.filter(
                    service=price.service, staff_level=twin
                ).first()
                if existing is not None and existing.amount != price.amount:
                    differing.append(price)
            if differing:
                level.name = f"{cat_name} (duplicate — review)"
                level.save(update_fields=["name"])
                conflicts += len(differing)
                self.stdout.write(
                    f"CONFLICT {cat_name}: {len(differing)} price(s) differ "
                    "from the named level — left in place for review."
                )
                continue
            for price in prices:
                existing = ServicePrice.objects.filter(
                    service=price.service, staff_level=twin
                ).first()
                if existing is not None:
                    price.delete()  # identical duplicate: the same fact
                else:
                    price.staff_level = twin
                    price.save(update_fields=["staff_level"])
            level.members.update(staff_level=twin)
            level.delete()
            merged += 1
        self.stdout.write(
            f"repair_staff_levels: salon={salon.name} merged={merged} "
            f"renamed={renamed} unassigned={unassigned} conflicts={conflicts}"
        )
