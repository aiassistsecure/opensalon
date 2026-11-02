"""Seed the staff-service capability matrix from the price book.

Materialises, for each salon, a ``StaffService`` row for every
(member, active service) pair that lacks one — enabled exactly
where the member's level is priced for the service, per
:func:`team.capabilities.seed_salon_capabilities`. Idempotent:
existing rows (the salon's own edits) are never flipped, so the
command is safe to re-run after the price book grows.
"""

from django.core.management.base import BaseCommand

from saloncore.models import Salon
from team.capabilities import seed_salon_capabilities


class Command(BaseCommand):
    help = "Seed staff-service capability rows from the price book."

    def add_arguments(self, parser):
        parser.add_argument(
            "--salon",
            default="",
            help="Only this salon (exact name). Default: every salon.",
        )

    def handle(self, *args, **options):
        salons = Salon.objects.order_by("id")
        if options["salon"]:
            salons = salons.filter(name=options["salon"])
        for salon in salons:
            created, enabled = seed_salon_capabilities(salon)
            self.stdout.write(
                f"seed_staff_services: salon={salon.name} "
                f"created={created} enabled={enabled}"
            )
