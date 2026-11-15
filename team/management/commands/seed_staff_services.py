"""Seed the staff-service capability matrix from the price book.

Usage:
    python manage.py seed_staff_services [--salon NAME]
        [--dry-run] [--format text|json]

With ``--format json`` the command prints exactly one JSON
object to stdout carrying the same facts as the text output
(per-salon created/enabled counts -- or, with ``--dry-run``,
per-salon and per-member would_create/would_enable counts --
and ``dry_run``); no prose lines are printed in json mode.
The default ``--format text`` output is unchanged.

Materialises, for each salon, a ``StaffService`` row for every
(member, active service) pair that lacks one — enabled exactly
where the member's level is priced for the service, per
:func:`team.capabilities.seed_salon_capabilities`. Idempotent:
existing rows (the salon's own edits) are never flipped, so the
command is safe to re-run after the price book grows.

With ``--dry-run`` no rows are created: the rows the seed
WOULD create are counted by staff member (and in total) and
printed, per :func:`team.capabilities.preview_seed_salon_capabilities`.
"""
import json

from django.core.management.base import BaseCommand, CommandError

from saloncore.models import Salon
from team.capabilities import (
    preview_seed_salon_capabilities,
    seed_salon_capabilities,
)


class Command(BaseCommand):
    help = "Seed staff-service capability rows from the price book."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon",
            default="",
            help="Only this salon (exact name). Default: every salon.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Preview StaffService rows the seed would create, "
                 "counted by staff member, and create none.")
        parser.add_argument(
            "--format", dest="format", default="text",
            choices=["text", "json"],
            help="Output format: text (default) or json.")

    def handle(self, *args, **options):
        fmt = options.get("format") or "text"
        if fmt not in ("text", "json"):
            raise CommandError(
                f"Invalid format {fmt!r}; expected 'text' or 'json'.")
        dry_run = bool(options.get("dry_run"))
        salons = Salon.objects.order_by("id")
        if options["salon"]:
            salons = salons.filter(name=options["salon"])
        results = []
        for salon in salons:
            if dry_run:
                created, enabled, per_member = (
                    preview_seed_salon_capabilities(salon))
                if fmt == "json":
                    results.append(dict(
                        salon=salon.name,
                        would_create=created,
                        would_enable=enabled,
                        per_member=[
                            dict(staff_member_id=member_id,
                                 would_create=mc,
                                 would_enable=me)
                            for member_id, (mc, me)
                            in per_member.items()
                        ]))
                    continue
                for member_id, (mc, me) in per_member.items():
                    self.stdout.write(
                        f"seed_staff_services dry-run: "
                        f"salon={salon.name} "
                        f"staff_member_id={member_id} "
                        f"would_create={mc} would_enable={me}")
                self.stdout.write(
                    f"seed_staff_services dry-run: salon={salon.name} "
                    f"would_create={created} would_enable={enabled} "
                    f"-- no rows created")
                continue
            created, enabled = seed_salon_capabilities(salon)
            if fmt == "json":
                results.append(dict(
                    salon=salon.name,
                    created=created,
                    enabled=enabled))
                continue
            self.stdout.write(
                f"seed_staff_services: salon={salon.name} "
                f"created={created} enabled={enabled}"
            )
        if fmt == "json":
            self.stdout.write(json.dumps(dict(
                salons=results,
                dry_run=dry_run)))
