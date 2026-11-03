"""Import roster patterns from a roster CSV file.

Usage:
    python manage.py import_roster roster.csv [--salon NAME]
    python manage.py import_roster roster.csv --dry-run

With ``--dry-run`` the file is loaded exactly as for a real
import but NOTHING is written (no salon or roster-pattern
rows): a JSON dry-run report from ``saloncore.dry_run`` is
printed to stdout instead -- per-key inferred types, distinct
null / missing / empty-string counts, and the source keys this
importer does not map -- extended with an ``import_preview``
(read-only counting twin of the writer, from
``team.roster_import.preview_roster_rows``): per-row
would-create / would-update / would-unchanged / would-refuse
counts, refused rows named by index and reason only, and the
command exits 0. The preview only reads: the salon is looked
up, never created, and the writer is never entered.

The input is a CSV with a header row. The canonical columns
are ``staff_member_external_id``, ``weekday``, ``start_time``
and ``end_time``; the spellings ``team.roster_export`` writes
(``staff_member_id`` / ``staff_name``) and the short forms
``member`` / ``start`` / ``end`` are also accepted -- see
:mod:`team.roster_import`, the service this command delegates
to, for the full mapping, the member-resolution rules
(external id scoped to the salon, the same active member set
``import_roster_derived`` uses), and the counted-skip rules.

Idempotent: writes are ``get_or_create`` on (member, weekday,
start, end) in the service, so re-running never duplicates and
an existing (human-corrected) pattern is never overwritten.
The import runs in one transaction, but that is
defence-in-depth only: on NEDB ``transaction.atomic()`` rolls
back nothing (DYOR section 9.4), so atomicity on NEDB rests on
bad rows being skipped/counted and on idempotent re-runs
healing any partial state. Output is counts only -- no staff
names are ever printed.
"""

import csv
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from saloncore.dry_run import build_dry_run_report
from saloncore.models import Salon
from team.roster_import import (
    MAPPED_KEYS, import_roster_rows, preview_roster_rows)


def _load_csv(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None:
                raise CommandError(
                    f"Roster file {path} is not valid CSV: "
                    f"missing header row.")
            return list(reader)
    except OSError as exc:
        raise CommandError(f"Cannot read roster file {path}: {exc}") from exc
    except csv.Error as exc:
        raise CommandError(
            f"Roster file {path} is not valid CSV: {exc}") from exc


class Command(BaseCommand):
    help = "Import roster patterns from a roster CSV export."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the roster CSV export.")
        parser.add_argument("--salon", default="My Salon",
                            help="Salon name to import into (created if missing).")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Print a JSON dry-run report (saloncore.dry_run) for "
                 "the source file plus a read-only import_preview "
                 "(would-create / would-update / would-unchanged / "
                 "would-refuse counts, refused rows by index) and "
                 "write nothing.")

    def handle(self, *args, **options):
        rows = _load_csv(options["path"])

        if options["dry_run"]:
            # Zero writes: the shape report is kept verbatim, then
            # extended with the read-only import preview (salon
            # lookup only -- no get_or_create, and
            # import_roster_rows below is never entered), then
            # return (exit 0).
            report = build_dry_run_report(
                rows, MAPPED_KEYS, source_name=options["path"])
            salon = Salon.objects.filter(name=options["salon"]).first()
            preview = preview_roster_rows(salon, rows)
            preview["salon"] = options["salon"]
            report["import_preview"] = preview
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
            return

        with transaction.atomic():
            salon, _ = Salon.objects.get_or_create(name=options["salon"])
            stats = import_roster_rows(salon, rows)

        self.stdout.write(
            "Imported roster for {salon}: {created} created, "
            "{existing} existing, {skipped} skipped.".format(
                salon=options["salon"], **stats))
        # Machine-readable line for validation runs (counts only).
        self.stdout.write("IMPORT_SUMMARY " + json.dumps(
            {"salon": options["salon"], **stats}, sort_keys=True))
