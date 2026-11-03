"""Seed the staff-service capability matrix from the price book.

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

from django.core.management.base import BaseCommand

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

    def handle(self, *args, **options):
        salons = Salon.objects.order_by("id")
        if options["salon"]:
            salons = salons.filter(name=options["salon"])
        for salon in salons:
            if options.get("dry_run"):
                created, enabled, per_member = (
                    preview_seed_salon_capabilities(salon))
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
            self.stdout.write(
                f"seed_staff_services: salon={salon.name} "
                f"created={created} enabled={enabled}"
            )
