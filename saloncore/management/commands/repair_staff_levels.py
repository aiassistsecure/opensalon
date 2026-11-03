"""Repair staff-level identity after a staff-less price import.

Usage:
    python manage.py repair_staff_levels --staff staff.json
        [--salon NAME] [--dry-run]

With ``--dry-run`` nothing is written: the same repair plan is
computed against an in-memory simulation of the levels and
prices (so a merge or rename earlier in the plan is seen by the
levels after it, exactly as a real run would see it), each
change the real run WOULD make is printed, and the summary
counts are the counts a real run over the same data produces.

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
        parser.add_argument("--dry-run", action="store_true",
                            help="Preview the merges, renames and "
                                 "conflicts a real run would make, "
                                 "with the same counts, and write "
                                 "nothing.")

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

        dry_run = bool(options.get("dry_run"))
        levels = list(StaffLevel.objects.filter(salon=salon))
        # Dry-run simulation state: simulated level names, deleted
        # level pks, and per-level price lists. Every lookup below
        # reads this state instead of the (unchanged) database, so
        # an earlier planned merge/rename is visible to later
        # levels exactly as the writes of a real run would be.
        sim_names = {}
        sim_deleted = set()
        sim_price_lists = {}

        def sim_name(level):
            return sim_names.get(level.pk, level.name)

        def sim_find(name, exclude_pk):
            for other in levels:
                if other.pk == exclude_pk or other.pk in sim_deleted:
                    continue
                if sim_name(other) == name:
                    return other
            return None

        def sim_prices(level_pk):
            if level_pk not in sim_price_lists:
                sim_price_lists[level_pk] = list(
                    ServicePrice.objects.filter(staff_level_id=level_pk))
            return sim_price_lists[level_pk]

        def sim_existing(twin_pk, service_id):
            for candidate in sim_prices(twin_pk):
                if candidate.service_id == service_id:
                    return candidate
            return None

        merged = renamed = unassigned = conflicts = 0
        for level in levels:
            if dry_run and level.pk in sim_deleted:
                continue
            name = sim_name(level) if dry_run else level.name
            if not _is_id_like(name):
                continue
            cat_name = categories.get(name.lower())
            if cat_name is None:
                label = f"Unassigned ····{name[-4:]}"
                if dry_run:
                    taken = sim_find(label, level.pk) is not None
                else:
                    taken = StaffLevel.objects.filter(
                        salon=salon, name=label
                    ).exclude(pk=level.pk).exists()
                if label != name and not taken:
                    if dry_run:
                        sim_names[level.pk] = label
                        self.stdout.write(
                            f"repair_staff_levels dry-run: would rename "
                            f"level '{name}' to '{label}'")
                    else:
                        level.name = label
                        level.save(update_fields=["name"])
                    unassigned += 1
                continue
            if dry_run:
                twin = sim_find(cat_name, level.pk)
            else:
                twin = (
                    StaffLevel.objects.filter(salon=salon, name=cat_name)
                    .exclude(pk=level.pk)
                    .first()
                )
            if twin is None:
                if dry_run:
                    sim_names[level.pk] = cat_name
                    self.stdout.write(
                        f"repair_staff_levels dry-run: would rename "
                        f"level '{name}' to '{cat_name}'")
                else:
                    level.name = cat_name
                    level.save(update_fields=["name"])
                renamed += 1
                continue
            if dry_run:
                prices = list(sim_prices(level.pk))
            else:
                prices = list(ServicePrice.objects.filter(staff_level=level))
            differing = []
            for price in prices:
                if dry_run:
                    existing = sim_existing(twin.pk, price.service_id)
                else:
                    existing = ServicePrice.objects.filter(
                        service=price.service, staff_level=twin
                    ).first()
                if existing is not None and existing.amount != price.amount:
                    differing.append(price)
            if differing:
                dup_label = f"{cat_name} (duplicate — review)"
                if dry_run:
                    sim_names[level.pk] = dup_label
                    self.stdout.write(
                        f"repair_staff_levels dry-run: would rename "
                        f"level '{name}' to '{dup_label}'")
                else:
                    level.name = dup_label
                    level.save(update_fields=["name"])
                conflicts += len(differing)
                self.stdout.write(
                    f"CONFLICT {cat_name}: {len(differing)} price(s) differ "
                    "from the named level — left in place for review."
                )
                continue
            if dry_run:
                for price in prices:
                    existing = sim_existing(twin.pk, price.service_id)
                    sim_prices(level.pk).remove(price)
                    if existing is None:
                        sim_prices(twin.pk).append(price)
                sim_deleted.add(level.pk)
                self.stdout.write(
                    f"repair_staff_levels dry-run: would merge "
                    f"level '{name}' into '{cat_name}'")
            else:
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
        if dry_run:
            self.stdout.write(
                f"repair_staff_levels dry-run: salon={salon.name} "
                f"merged={merged} renamed={renamed} "
                f"unassigned={unassigned} conflicts={conflicts} "
                f"-- no changes written"
            )
            return
        self.stdout.write(
            f"repair_staff_levels: salon={salon.name} merged={merged} "
            f"renamed={renamed} unassigned={unassigned} conflicts={conflicts}"
        )
