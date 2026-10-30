"""Import staff members from a staff JSON extract.

Usage:
    python manage.py import_staff staff.json [--salon NAME]

The input is a JSON list of staff objects in the source system's own
shape: ``staffId``, ``firstName`` and ``lastName`` (a single ``name``
or ``displayName`` is also accepted), plus other fields this command
deliberately does not map.

Mapping (one source of truth — this command is the only writer here):

- StaffMember <- ``firstName`` + ``lastName`` joined into
  ``display_name`` (truncated to the model's field length).
- Natural key: ``staffId`` (fallback: ``id``), stored on the generic
  ``StaffMember.external_id`` field (never a provider-named column)
  and scoped to the salon. This is the id appointments carry as their
  staff reference, so storing any other id would leave appointments
  unresolvable. Records without a stable id, or without any name,
  are skipped and counted — never imported with a guessed key or a
  stand-in name.
- Levels and roles are left untouched: ``staff_level``,
  ``online_bookable`` and ``active`` are not in the update defaults,
  so an import never clears or invents them. On creation they take
  the model's own defaults; the source's category name is not mapped
  to a StaffLevel here because a category label is not proof of a
  level assignment in OpenSalon's price book.

Idempotent: rows are written with ``update_or_create`` keyed by
(salon, external_id), so re-running updates in place and never
duplicates. The import runs in one transaction: a bad file changes
nothing. Output is counts only — no staff names are ever printed.
"""

import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from saloncore.models import Salon
from team.models import StaffMember


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        raise CommandError(f"Cannot read staff file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CommandError(f"Staff file {path} is not valid JSON: {exc}") from exc


def _text(row, key, limit):
    value = row.get(key)
    return str(value).strip()[:limit] if value else ""


def _display_name(row):
    combined = " ".join(
        part for part in (_text(row, "firstName", 120),
                          _text(row, "lastName", 120)) if part)
    return (combined or _text(row, "displayName", 120)
            or _text(row, "name", 120))[:120]


class Command(BaseCommand):
    help = "Import staff members from a staff JSON export."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the staff JSON export.")
        parser.add_argument("--salon", default="My Salon",
                            help="Salon name to import into (created if missing).")

    def handle(self, *args, **options):
        data = _load_json(options["path"])
        if isinstance(data, dict):
            data = data.get("staff", data.get("staffMembers", []))
        if not isinstance(data, list):
            raise CommandError("Staff file must be a JSON list of staff.")

        stats = dict.fromkeys(["created", "updated", "skipped"], 0)
        with transaction.atomic():
            salon, _ = Salon.objects.get_or_create(name=options["salon"])
            for row in data:
                if not isinstance(row, dict):
                    stats["skipped"] += 1
                    continue
                external_id = _text(row, "staffId", 64) or _text(row, "id", 64)
                display_name = _display_name(row)
                if not external_id or not display_name:
                    stats["skipped"] += 1
                    continue
                _, created = StaffMember.objects.update_or_create(
                    salon=salon, external_id=external_id,
                    defaults={"display_name": display_name})
                stats["created" if created else "updated"] += 1

        self.stdout.write(
            "Imported staff for {salon}: {created} created, "
            "{updated} updated, {skipped} skipped.".format(
                salon=options["salon"], **stats))
        # Machine-readable line for validation runs (counts only).
        self.stdout.write("IMPORT_SUMMARY " + json.dumps(
            {"salon": options["salon"], **stats}, sort_keys=True))
